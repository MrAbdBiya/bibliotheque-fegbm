document.addEventListener('DOMContentLoaded', () => {
    // Éléments DOM
    const searchInput = document.querySelector('.search-input input');
    const searchSelect = document.querySelector('.search-filters select');
    const searchButton = document.querySelector('.btn-search');
    const languageSelect = document.querySelector('.language-select');

    // Fonction de recherche
    function performSearch() {
        const query = searchInput.value.trim();
        const category = searchSelect.value;
        
        if (!query) {
            showNotification('Veuillez entrer un terme de recherche', 'error');
            return;
        }

        // Simuler une recherche (à remplacer par une vraie API)
        showNotification('Recherche en cours...', 'info');
        
        // Ici, vous pouvez ajouter l'appel à votre API de recherche
        console.log('Recherche:', { query, category });
    }

    // Gestionnaire d'événements pour le bouton de recherche
    searchButton.addEventListener('click', performSearch);

    // Gestionnaire d'événements pour la touche Entrée dans le champ de recherche
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            performSearch();
        }
    });

    // Gestionnaire pour le changement de langue
    languageSelect.addEventListener('change', (e) => {
        const language = e.target.value;
        changeLanguage(language);
    });

    // Fonction pour changer la langue
    function changeLanguage(language) {
        // Ici, vous pouvez ajouter la logique pour changer la langue
        console.log('Changement de langue:', language);
    }

    // Système de notification
    function showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;

        // Supprimer les notifications existantes
        const existingNotifications = document.querySelectorAll('.notification');
        existingNotifications.forEach(notif => notif.remove());

        // Ajouter la nouvelle notification
        document.body.appendChild(notification);

        // Supprimer la notification après 3 secondes
        setTimeout(() => {
            notification.remove();
        }, 3000);
    }

    // Animation des cartes d'accès rapide
    const quickAccessCards = document.querySelectorAll('.quick-access-card');
    quickAccessCards.forEach(card => {
        card.addEventListener('click', () => {
            card.classList.add('card-clicked');
            setTimeout(() => {
                card.classList.remove('card-clicked');
            }, 200);
        });
    });

    // Gestion du menu mobile
    const mobileMenuButton = document.createElement('button');
    mobileMenuButton.className = 'mobile-menu-button';
    mobileMenuButton.innerHTML = '<i class="fas fa-bars"></i>';
    document.querySelector('.main-nav').prepend(mobileMenuButton);

    mobileMenuButton.addEventListener('click', () => {
        document.querySelector('.main-nav ul').classList.toggle('show');
    });

    // Gestion du scroll
    let lastScroll = 0;
    window.addEventListener('scroll', () => {
        const currentScroll = window.pageYOffset;
        const header = document.querySelector('.main-header');

        if (currentScroll > lastScroll && currentScroll > 100) {
            header.classList.add('header-hidden');
        } else {
            header.classList.remove('header-hidden');
        }
        lastScroll = currentScroll;
    });

    // Lazy loading des images
    const images = document.querySelectorAll('img[data-src]');
    const imageObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.dataset.src;
                img.removeAttribute('data-src');
                observer.unobserve(img);
            }
        });
    });

    images.forEach(img => imageObserver.observe(img));

    // Animations au scroll
    const animatedElements = document.querySelectorAll('.animate-on-scroll');
    const elementObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animated');
            }
        });
    });

    animatedElements.forEach(element => elementObserver.observe(element));

    // Gestion du mode sombre
    const darkModeToggle = document.createElement('button');
    darkModeToggle.className = 'dark-mode-toggle';
    darkModeToggle.innerHTML = '<i class="fas fa-moon"></i>';
    document.querySelector('.header-actions').prepend(darkModeToggle);

    darkModeToggle.addEventListener('click', () => {
        document.body.classList.toggle('dark-mode');
        const isDarkMode = document.body.classList.contains('dark-mode');
        darkModeToggle.innerHTML = isDarkMode ? '<i class="fas fa-sun"></i>' : '<i class="fas fa-moon"></i>';
        localStorage.setItem('darkMode', isDarkMode);
    });

    // Vérifier la préférence de mode sombre
    if (localStorage.getItem('darkMode') === 'true') {
        document.body.classList.add('dark-mode');
        darkModeToggle.innerHTML = '<i class="fas fa-sun"></i>';
    }
});
