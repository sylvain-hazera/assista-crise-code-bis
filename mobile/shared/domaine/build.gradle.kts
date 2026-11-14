import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlin.multiplatform)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    jvm {
        compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
    }
    // iPhone et simulateur. Ces cibles ne se compilent que sur macOS : ici elles sont
    // ignorees, et c'est l'integration continue (.github/workflows/mobile-ios.yml) qui
    // verifie que le code partage reste compilable pour iOS.
    iosArm64()
    iosSimulatorArm64()

    sourceSets {
        commonMain.dependencies {
            api(libs.coroutines.core)
            api(libs.serialization.json)

        }
        commonTest.dependencies {
            implementation(kotlin("test"))
            implementation(libs.coroutines.test)

        }
    }
}
