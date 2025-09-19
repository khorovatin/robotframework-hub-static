import importlib.metadata
import json
import os
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


def generate_doc_file(lib_file_or_resource: str, out_dir: str, out_file: str, lib_name: str) -> Dict:
    """Generates a doc file and returns a dictionary of its keywords."""
    result_dict = {}
    out = StringIO()
    err = StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = libdoc_instance.execute_cli([lib_file_or_resource, 'list'], exit=False)
    output_text = out.getvalue().strip()
    output_lines = output_text.split('\n') if output_text else []
    if rc == 0 and len(output_lines) > 0:
        if not os.path.exists(os.path.dirname(out_file)):
            os.makedirs(os.path.dirname(out_file))
        lib_base_name = os.path.basename(lib_name)
        with redirect_stdout(out), redirect_stderr(err):
            result = libdoc_instance.execute(lib_file_or_resource, out_file, name=lib_base_name)
        if result != 0 and os.path.exists(out_file):
            os.remove(out_file)
        if os.path.exists(out_file):
            keywords_list = []
            rel_path = os.path.relpath(out_file, out_dir).replace(os.sep, '/')
            base_url = quote(rel_path)
            for _line in sorted(output_lines):
                _line_url = quote(_line)
                keywords_list.append({"name": _line, "url": f"{base_url}#{_line_url}"})
            result_dict[lib_name] = {
                "name": lib_name, "keywords": keywords_list,
                "path": lib_file_or_resource, "url": base_url
            }
            print(f"Created documentation for '{lib_name}' with {len(keywords_list)} keywords.")
    out.close()
    err.close()
    return result_dict


def generate_doc_builtin(out_path: str) -> Dict:
    """Generates documentation for Robot Framework's built-in libraries."""
    result_dict = {}
    print("\nProcessing Built-in Libraries...")
    for lib in sorted(STDLIBS):
        if lib not in ['Easter', 'Reserved']:
            file_path = os.path.join(out_path, f"{lib}.html")
            result_dict.update(generate_doc_file(lib, out_path, file_path, lib))
    return result_dict


def get_robot_modules() -> List[str]:
    """Finds installed Python packages that are Robot Framework libraries."""
    library_names = []
    for dist in importlib.metadata.distributions():
        is_robot_lib = any('robotframework' in req for req in (dist.requires or []))
        if is_robot_lib:
            for file in dist.files or []:
                if file.suffix == '.py' and file.parts:
                    lib_name = file.parts[0]
                    if lib_name not in library_names and not lib_name.startswith('rfhub'):
                        library_names.append(lib_name)
    return sorted(list(set(library_names)))


def generate_doc_libraries(out_path: str) -> Dict:
    """Generates documentation for all installed Robot Framework libraries."""
    result_dict = {}
    found_modules = get_robot_modules()
    print(f"\nProcessing {len(found_modules)} Installed Libraries: {found_modules}")
    for lib_name in found_modules:
        out_file = os.path.join(out_path, f"{lib_name}.html")
        result_dict.update(generate_doc_file(lib_name, out_path, out_file, lib_name))
    return result_dict


def get_resource_file_list(directory_path: str) -> List[str]:
    """Recursively finds all Robot Framework resource files in a directory."""
    file_list = []
    if not os.path.isdir(directory_path):
        return []
    for root, _, files in os.walk(directory_path):
        for name in files:
            if os.path.splitext(name)[1] in ['.resource', '.txt', '.py', '.robot']:
                file_list.append(os.path.join(root, name))
    return file_list


def generate_doc_from_path(in_path: str, out_path: str, category_name: str) -> Dict:
    """Generic function to generate docs for a category from a given input path."""
    print(f"\nProcessing {category_name} from '{in_path}'...")
    file_list = get_resource_file_list(in_path)
    result_dict = {}
    in_path_full = os.path.abspath(in_path)
    out_path_full = os.path.abspath(out_path)

    for file in sorted(file_list):
        rel_path_to_file = os.path.relpath(file, in_path_full)
        base_name, _ = os.path.splitext(rel_path_to_file)
        # Place generated files in a subdirectory named after their category
        out_file = os.path.join(out_path_full, category_name, f"{base_name}.html")
        resource_name = rel_path_to_file
        result_dict.update(generate_doc_file(file, out_path_full, out_file, resource_name))
    return result_dict


def _build_resource_tree(resource_list: List[Dict]) -> Dict[str, Any]:
    """Converts a flat list of resources into a nested dictionary for the tree view."""
    tree = {}
    for resource in resource_list:
        parts = resource["name"].replace("\\", "/").split("/")
        current_level = tree
        for part in parts[:-1]:
            current_level = current_level.setdefault(part, {})
        file_list = current_level.setdefault("__files__", [])
        file_list.append((parts[-1], resource))
    return tree


def create_index_page(out_path: str, template_directory: str, all_docs: Dict) -> None:
    """Creates the main index.html file with embedded search data and hierarchical trees."""
    search_data = []
    # Consolidate all keywords from all categories for the search index
    for category_items in all_docs.values():
        for item in category_items:
            for kw in item.get('keywords', []):
                search_data.append({'name': kw['name'], 'url': kw['url'], 'library': item['name']})

    search_json = json.dumps(search_data, indent=None)

    resource_tree = _build_resource_tree(all_docs.get("resources", []))
    page_object_tree = _build_resource_tree(all_docs.get("page_objects", []))

    env = Environment(loader=FileSystemLoader(template_directory), autoescape=select_autoescape(['html']))
    template = env.get_template("index.html")

    result = template.render(
        data={
            "version": pkg_version,
            "libraries": all_docs.get("libraries", []),
            "resource_tree": resource_tree,
            "page_object_tree": page_object_tree,
            "search_json": search_json
        }
    )
    with open(os.path.join(out_path, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(result)
    print("\nCreated index.html successfully.")


def do_it(input_paths: List[str], out_path: str) -> None:
    """Main execution function to generate all documentation."""
    for path in input_paths:
        if not os.path.isdir(path):
            sys.exit(f"ERROR: Input path '{path}' not found or is not a directory.")

    if os.path.exists(out_path):
        shutil.rmtree(out_path)
    os.makedirs(out_path)

    pkg_dir = os.path.dirname(os.path.realpath(__file__))
    shutil.copytree(os.path.join(pkg_dir, 'static'), os.path.join(out_path, 'static'), dirs_exist_ok=True)

    # Correctly combine built-in and installed libraries into a single dictionary
    lib_dict = {**generate_doc_builtin(out_path), **generate_doc_libraries(out_path)}

    # Process Resources and Page Objects from their respective paths
    res_dict = generate_doc_from_path(input_paths[0], out_path, "resources") if len(input_paths) > 0 else {}
    po_dict = generate_doc_from_path(input_paths[1], out_path, "page_objects") if len(input_paths) > 1 else {}

    # Consolidate all documentation into a single structure
    all_docs = {
        "libraries": sorted(lib_dict.values(), key=lambda x: x['name']),
        "resources": sorted(res_dict.values(), key=lambda x: x['name']),
        "page_objects": sorted(po_dict.values(), key=lambda x: x['name'])
    }

    create_index_page(out_path, os.path.join(pkg_dir, 'templates'), all_docs)
    print('\nGeneration complete.')


def kw_doc_gen():
    """CLI entry point."""
    if len(sys.argv) < 3:
        prg_name = os.path.basename(sys.argv[0])
        print(f"Usage: {prg_name} <output_directory> <resources_path> [<page_objects_path>]")
        print("\nExample:")
        print(f"  {prg_name} docs/ my_project/resources/ my_project/pages/")
        sys.exit(2)

    # Correctly parse arguments: output dir is first, followed by input paths
    do_it(sys.argv[2:], sys.argv[1])


if __name__ == '__main__':
    kw_doc_gen()

