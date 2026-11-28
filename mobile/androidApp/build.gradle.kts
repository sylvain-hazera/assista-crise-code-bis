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
        // Chaque APK publié prend un numéro de plus : c'est lui que l'application compare à
        // /mobile/version.json pour proposer la mise à jour (scripts/publier-mobile.sh).
        versionCode = 62
        versionName = "0.39.0"
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
            // L'hote des QR codes de mobilisation : l'application propose de les ouvrir elle-meme.
            manifestPlaceholders["hoteSite"] = site.substringAfter("://").substringBefore("/").substringBefore(":")
            // Sans accent : ce nom part dans les metadonnees des photos (EXIF).
            buildConfigField("String", "NOM_MARQUE", "\"Reserve Resilience\"")
            // Sa clé dans /mobile/version.json (`applications`).
            buildConfigField("String", "CLE_APPLICATION", "\"reserve-resilience\"")
            buildConfigField("String", "NOM_MARQUE_AFFICHE", "\"Réserve Résilience\"")
        }
        // Assista-Crise : la meme application, sous sa propre marque (embleme a la flamme, sarcelle
        // et anthracite), servie par www.assista-crise.fr et qui parle a ce domaine-la. Les deux
        // applications s'installent cote a cote : identifiants distincts.
        // Images : src/assistaCrise/res ; palette : src/assistaCrise/kotlin/.../ui/Marque.kt.
        create("assistaCrise") {
            dimension = "marque"
            applicationId = "fr.assista_crise.app"
            resValue("string", "nom_application", "Assista-Crise")
            val site = (project.findProperty("urlSite") as String?) ?: "https://www.assista-crise.fr"
            buildConfigField("String", "URL_SITE", "\"$site\"")
            buildConfigField("String", "URL_API", "\"$site/api\"")
            manifestPlaceholders["hoteSite"] = site.substringAfter("://").substringBefore("/").substringBefore(":")
            buildConfigField("String", "NOM_MARQUE", "\"Assista-Crise\"")
            buildConfigField("String", "CLE_APPLICATION", "\"assista-crise\"")
            buildConfigField("String", "NOM_MARQUE_AFFICHE", "\"Assista-Crise\"")
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
    // Lire et dessiner les QR codes sur le telephone meme, sans service d'un fabricant.
    implementation(libs.camera.core)
    implementation(libs.camera.camera2)
    implementation(libs.camera.lifecycle)
    implementation(libs.camera.view)
    implementation(libs.zxing)
}
