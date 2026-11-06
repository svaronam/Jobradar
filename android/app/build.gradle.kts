plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.svaronam.jobradar"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.svaronam.jobradar"
        minSdk = 26
        targetSdk = 34
        versionCode = 4
        versionName = "1.2.1"
    }

    // Firma fija: cada APK nueva de GitHub Actions se instala encima de la anterior sin desinstalar.
    signingConfigs {
        create("fija") {
            storeFile = file("keystore/jobradar.jks")
            storePassword = System.getenv("KEYSTORE_PASSWORD")
            keyAlias = "jobradar"
            keyPassword = System.getenv("KEYSTORE_PASSWORD")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("fija")
        }
        debug {
            signingConfig = signingConfigs.getByName("fija")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation("androidx.core:core-ktx:1.13.1")
}
