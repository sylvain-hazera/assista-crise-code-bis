plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "fr.assistacrise.mobile"
    compileSdk = 35

    defaultConfig {
        minSdk = 26
        targetSdk = 35
        versionCode = 6
        versionName = "0.5.0"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    // Une marque = une saveur : identifiant d'application, nom, adresse du serveur. Le
    // serveur habille deja ses reponses selon le domaine appele (core/branding.py) ;
    // l'application n'a donc qu'a appeler le bon domaine. Logo et couleurs sont, eux, figes
    // dans le binaire : une application ne peut pas attendre le reseau pour savoir a quoi
    // elle ressemble.
    flavorDimensions += "marque"
    productFlavors {
        create("reserveResilience") {
            dimension = "marque"
            applicationId = "org.reserve_resilience.app"
            resValue("string", "nom_application", "Réserve Résilience")
            // -PurlSite=http://10.0.2.2:8000 pour viser un serveur de developpement.
            val site = (project.findProperty("urlSite") as String?) ?: "https://app.reserve-resilience.org"
            buildConfigField("String", "URL_SITE", "\"$site\"")
            buildConfigField("String", "URL_API", "\"$site/api\"")
        }
    }

    buildTypes {
        // La carte embarque du code natif, une copie par architecture de processeur. Les
        // telephones d'aujourd'hui sont en arm64 ; armeabi-v7a couvre les plus anciens.
        // x86_64 n'existe que pour l'emulateur, donc en developpement seulement.
        debug {
            // -Pabis=arm64-v8a pour un APK leger destine a un seul telephone recent.
            val abis = (project.findProperty("abis") as String?)?.split(",") ?: listOf("arm64-v8a", "armeabi-v7a", "x86_64")
            ndk { abiFilters += abis }
        }
        release {
            isMinifyEnabled = false
            ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    packaging {
        resources.excludes += setOf("META-INF/INDEX.LIST", "META-INF/*.kotlin_module", "META-INF/AL2.0", "META-INF/LGPL2.1")
    }
}

dependencies {
    implementation(project(":shared:domaine"))
    implementation(project(":shared:donnees"))
    implementation(project(":shared:lien"))

    implementation(libs.coroutines.android)
    implementation(libs.ktor.client.core)
    implementation(libs.ktor.client.okhttp)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.maplibre)
    implementation(libs.work.runtime)
    implementation(libs.exifinterface)
}
