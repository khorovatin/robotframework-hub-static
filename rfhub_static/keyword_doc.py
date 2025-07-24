import importlib.metadata
import json  # Import the json library
import os
import re
import shutil
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import Any, Dict, List
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape
from robot.libdoc import LibDoc
from robot.libraries import STDLIBS
from robot.output.logger import LOGGER

from rfhub_static.version import __version__ as pkg_version

libdoc_instance = LibDoc()
LOGGER.unregister_console_logger()


def generate_doc_file(
    lib_file_or_resource: str, out_dir: str, out_file: str, lib_name: str
) -> Dict:
    result_dict = {}
    out = StringIO()
    err = StringIO()

    with redirect_stdout(out), redirect_stderr(err):
        # Use 'list' command to get a list of keywords
        rc = libdoc_instance.execute_cli([lib_file_or_resource, "list"], exit=False)
    output_text = out.getvalue().strip()
    output_lines = output_text.split("\n") if output_text else []

    if rc == 0 and len(output_lines) > 0:
        if not os.path.exists(os.path.dirname(out_file)):
            os.makedirs(os.path.dirname(out_file))

        lib_base_name = os.path.basename(lib_name)
        with redirect_stdout(out), redirect_stderr(err):
            # Generate the actual documentation file
            result = libdoc_instance.execute(
                lib_file_or_resource, out_file, name=lib_base_name
            )

        if result != 0 and os.path.exists(out_file):
            os.remove(out_file)  # Clean up failed doc files

        if os.path.exists(out_file):
            keywords_list = []
            rel_path = os.path.relpath(out_file, out_dir).replace(os.sep, "/")
            base_url = quote(rel_path)
            for line in sorted(output_lines):
                line_url = quote(line)
                keywords_list.append({"name": line, "url": f"{base_url}#{line_url}"})

            result_dict[lib_name] = {
                "name": lib_name,
                "keywords": keywords_list,
                "path": lib_file_or_resource,
                "url": base_url,
            }
            print(f"Created {out_file} with {len(keywords_list)} keywords.")
    out.close()
    err.close()
    return result_dict


def generate_doc_builtin(out_path: str) -> Dict:
    result_dict = {}
    for lib in sorted(STDLIBS):
        if lib not in ["Easter", "Reserved"]:
            file_name_rel = f"{lib}.html"
            file_path = os.path.join(out_path, file_name_rel)
            result_dict.update(generate_doc_file(lib, out_path, file_path, lib))
    return result_dict


def get_robot_modules() -> List[str]:
    distributions = importlib.metadata.distributions()
    library_names = []
    for dist in distributions:
        is_robot_lib = False
        if (
            dist.metadata.get("Name")
            and "robotframework" in dist.metadata["Name"]
            and dist.metadata["Name"] != "robotframework"
        ):
            is_robot_lib = True
        if not is_robot_lib and dist.requires:
            is_robot_lib = any(
                "robotframework" == req.split(" ")[0] for req in dist.requires
            )
        if is_robot_lib:
            for file in dist.files or []:
                if file.suffix == ".py":
                    lib_name = file.parts[0]
                    if lib_name not in library_names and not re.match(
                        r"^rfhub.*", lib_name
                    ):
                        library_names.append(lib_name)
    return sorted(list(set(library_names)))


def generate_doc_libraries(out_path: str) -> Dict:
    result_dict = {}
    for lib_name in get_robot_modules():
        out_file = os.path.join(out_path, f"{lib_name}.html")
        result_dict.update(generate_doc_file(lib_name, out_path, out_file, lib_name))
    return result_dict


def get_resource_file_list(
    directory_path: str, exclude_patterns: List[str]
) -> List[str]:
    ignore_file = os.path.join(directory_path, ".rfhubignore")
    patterns = exclude_patterns.copy()
    if os.path.exists(ignore_file):
        with open(ignore_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)

    file_list = []
    for root, _, files in os.walk(directory_path):
        # Exclude directories matching patterns
        if any(re.search(p, os.path.basename(root)) for p in patterns):
            continue
        for name in files:
            if any(re.search(p, name) for p in patterns):
                continue
            if os.path.splitext(name)[1] in [".resource", ".py"]:
                file_list.append(os.path.join(root, name))
    return file_list


def generate_doc_resource_files(in_path: str, out_path: str) -> Dict:
    file_list = get_resource_file_list(in_path, [])
    result_dict = {}
    in_path_full = os.path.abspath(in_path)
    out_path_full = os.path.abspath(out_path)

    for file in sorted(file_list):
        rel_path_to_file = os.path.relpath(file, in_path_full)
        base_name, ext = os.path.splitext(rel_path_to_file)
        out_file = os.path.join(out_path_full, f"{base_name}.html")

        resource_name = rel_path_to_file
        result_dict.update(generate_doc_file(file, out_path, out_file, resource_name))
    return result_dict


def _build_resource_tree(resource_list: List[Dict]) -> Dict[str, Any]:
    """Converts a flat list of resources into a nested dictionary representing the folder tree."""
    tree = {}
    for resource in resource_list:
        # Normalize path and split into parts
        parts = resource["name"].replace("\\", "/").split("/")
        current_level = tree
        for part in parts[:-1]:  # Iterate through directories
            current_level = current_level.setdefault(part, {})

        # Use a special key to store files within a directory
        file_list = current_level.setdefault("__files__", [])
        file_list.append((parts[-1], resource))
    return tree


def create_index_page(
    out_path: str, template_directory: str, library_list: List, resource_list: List
) -> None:
    """
    Creates the main index.html file, embedding search data directly to avoid fetch errors.
    """
    # Aggregate all keywords into a single list for the search index
    search_data = []
    for lib in library_list:
        for kw in lib.get("keywords", []):
            search_data.append(
                {"name": kw["name"], "url": kw["url"], "library": lib["name"]}
            )
    for res in resource_list:
        for kw in res.get("keywords", []):
            search_data.append(
                {"name": kw["name"], "url": kw["url"], "library": res["name"]}
            )

    # Convert the search data to a JSON string
    search_json = json.dumps(search_data)

    # Build the resource tree
    resource_tree = _build_resource_tree(resource_list)

    env = Environment(
        loader=FileSystemLoader(template_directory),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("index.html")  # Use a new 'index.html' template

    result = template.render(
        data={
            "version": pkg_version,
            "libraries": library_list,
            "resource_tree": resource_tree,
            "search_json": search_json,  # Pass the JSON string to the template
        }
    )

    with open(os.path.join(out_path, "index.html"), "w", encoding="utf-8") as f:
        f.write(result)
    print("Created index.html with hierarchical navigation.")


# New function to create the search index
def create_search_index(out_path: str, libraries: List, resources: List) -> None:
    all_keywords = []
    # Aggregate keywords from libraries
    for lib in libraries:
        for kw in lib.get("keywords", []):
            all_keywords.append(
                {
                    "name": kw["name"],
                    "url": kw["url"],
                    "library": lib["name"],
                    "doc": "",  # Placeholder for keyword documentation if available later
                }
            )
    # Aggregate keywords from resources
    for res in resources:
        for kw in res.get("keywords", []):
            all_keywords.append(
                {
                    "name": kw["name"],
                    "url": kw["url"],
                    "library": res["name"],
                    "doc": "",  # Placeholder
                }
            )

    index_path = os.path.join(out_path, "search_index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(all_keywords, f)
    print(f"Created search index with {len(all_keywords)} keywords at {index_path}")


def do_it(in_path: str, out_path: str) -> None:
    # Error handling and path cleanup
    if not os.path.exists(in_path) or not os.path.isdir(in_path):
        print(f"ERROR: Specified base path '{in_path}' is not a valid directory.")
        sys.exit(2)
    if out_path == "/":
        print("ERROR: Target directory cannot be the root directory.")
        sys.exit(2)

    if os.path.exists(out_path):
        shutil.rmtree(out_path)
    os.makedirs(out_path)

    package_base_directory = os.path.dirname(os.path.realpath(__file__))
    template_directory = os.path.join(package_base_directory, "templates")
    static_src = os.path.join(package_base_directory, "static")
    static_dst = os.path.join(out_path, "static")
    # Ensure the static destination exists before copying
    os.makedirs(static_dst, exist_ok=True)
    shutil.copytree(static_src, static_dst, dirs_exist_ok=True)

    builtin_dict = generate_doc_builtin(out_path)
    library_dict = generate_doc_libraries(out_path)
    resource_dict = generate_doc_resource_files(in_path, out_path)

    all_libraries = {**builtin_dict, **library_dict}
    all_libraries_sorted = [all_libraries[key] for key in sorted(all_libraries)]
    all_resources_sorted = [resource_dict[key] for key in sorted(resource_dict)]

    # Call the updated index page function
    create_index_page(
        out_path, template_directory, all_libraries_sorted, all_resources_sorted
    )

    print("Done")


def kw_doc_gen():
    if sys.version_info < (3, 6):
        print(f"{sys.argv[0]} requires Python 3.6 or newer.")
        sys.exit(1)

    if len(sys.argv) < 3:
        prg_name = os.path.basename(sys.argv[0])
        print(f"Usage: {prg_name} <base_directory> <documentation_directory>")
        # ... (rest of the usage message)
        sys.exit(2)

    in_path = sys.argv[1]
    out_path = sys.argv[2]
    do_it(in_path, out_path)


if __name__ == "__main__":
    kw_doc_gen()
