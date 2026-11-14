pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "assista-crise-mobile"

// La logique vit dans :shared, en Kotlin Multiplatform (voir DOSSIER-APPLICATION-INTERVENANTS.md
// § 3). Seule cible compilee aujourd'hui : la JVM, que l'application Android consomme telle
// quelle. Ajouter iOS, c'est ajouter des cibles ici, pas reecrire.
include(":shared:domaine")
include(":shared:donnees")
include(":shared:lien")
include(":androidApp")
