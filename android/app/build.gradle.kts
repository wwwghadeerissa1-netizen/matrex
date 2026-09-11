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

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}
