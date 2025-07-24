document.addEventListener('DOMContentLoaded', function () {
    const navTree = document.getElementById('nav-tree');
    
    // Use event delegation to handle clicks on all toggle elements
    navTree.addEventListener('click', function (e) {
        if (e.target.classList.contains('toggle')) {
            // Toggle the 'collapsed' class on the parent <li> element
            e.target.parentElement.classList.toggle('collapsed');
        }
    });

    const searchInput = document.getElementById('search-input');
    const searchResultsContainer = document.getElementById('search-results');
    const keywordNavigationContainer = document.getElementById('keyword-navigation');
    
    // Ensure the search data embedded in the HTML is available
    if (typeof RFW_SEARCH_DATA === 'undefined') {
        console.error("Search data (RFW_SEARCH_DATA) not found in the page.");
        return;
    }

    const documents = RFW_SEARCH_DATA;
    const lunrIndex = lunr(function () {
        this.ref('url');
        this.field('name', { boost: 10 });
        this.field('library');
        documents.forEach(doc => this.add(doc));
    });

    // Handle user input in the search field
    searchInput.addEventListener('input', function (e) {
        const query = e.target.value.trim().toLowerCase();

        if (query.length < 2) {
            searchResultsContainer.style.display = 'none';
            keywordNavigationContainer.style.display = 'block';
            return;
        }

        const results = lunrIndex.search(query);
        keywordNavigationContainer.style.display = 'none';
        searchResultsContainer.style.display = 'block';
        displayResults(results);
    });

    function displayResults(results) {
        searchResultsContainer.innerHTML = '';
        if (results.length === 0) {
            searchResultsContainer.innerHTML = '<div class="no-results">No keywords found.</div>';
            return;
        }
        const ul = document.createElement('ul');
        results.slice(0, 100).forEach(result => {
            const item = documents.find(doc => doc.url === result.ref);
            if (item) {
                const li = document.createElement('li');
                li.innerHTML = `<a href="${item.url}" target="doc-frame">${item.name} <span class="library-name">(${item.library})</span></a>`;
                ul.appendChild(li);
            }
        });
        searchResultsContainer.appendChild(ul);
    }
});
