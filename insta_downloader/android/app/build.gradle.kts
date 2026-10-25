plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// GitHub Actions 에서는 실행 번호를 버전으로 써서 매 빌드가 업데이트로 설치되게 한다
val buildNumber = System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull() ?: 1

// 서명 키(release.jks)가 있으면 그걸로, 없으면 디버그 키로 서명한다.
// 같은 키로 서명해야 앱을 지우지 않고 업데이트할 수 있다 (README 참고).
val releaseKeystore = file("release.jks")

android {
    namespace = "kr.instasaver"
    compileSdk = 35

    defaultConfig {
        applicationId = "kr.instasaver"
        minSdk = 29
        targetSdk = 35
        versionCode = buildNumber
        versionName = "1.0.$buildNumber"
    }

    signingConfigs {
        create("release") {
            if (releaseKeystore.exists()) {
                storeFile = releaseKeystore
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KEY_ALIAS")
                keyPassword = System.getenv("KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            // yt-dlp 라이브러리가 리플렉션(jackson)을 써서 코드 축소는 끈다
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName(if (releaseKeystore.exists()) "release" else "debug")
        }
    }

    // 파이썬·ffmpeg 네이티브 바이너리가 커서 CPU 종류별로 APK 를 나눈다
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64")
            isUniversalApk = false
        }
    }

    // youtubedl-android 는 압축 해제된 네이티브 라이브러리가 필요하다
    packaging {
        jniLibs { useLegacyPackaging = true }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    lint {
        checkReleaseBuilds = false
    }
}

dependencies {
    implementation("io.github.junkfood02.youtubedl-android:library:0.18.1")
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:0.18.1")

    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("com.google.android.material:material:1.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
}
