plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.matrex.repair"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.matrex.repair"
        minSdk = 26
        targetSdk = 35
        versionCode = 3
        versionName = "2.0.0"
    }

    signingConfigs {
        create("release") {
            val keystorePath = project.findProperty("matrexKeystorePath") as String?
            val keystorePassword = project.findProperty("matrexKeystorePassword") as String?
            val keyAlias = project.findProperty("matrexKeyAlias") as String?
            val keyPassword = project.findProperty("matrexKeyPassword") as String?
            if (!keystorePath.isNullOrBlank() && !keystorePassword.isNullOrBlank() && !keyAlias.isNullOrBlank() && !keyPassword.isNullOrBlank()) {
                storeFile = file(keystorePath)
                storePassword = keystorePassword
                this.keyAlias = keyAlias
                this.keyPassword = keyPassword
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = false
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
