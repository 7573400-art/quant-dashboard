package kr.instasaver

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File

/** 갤러리에 저장된 결과 하나 */
data class SavedMedia(val uri: Uri, val name: String, val mime: String)

/**
 * yt-dlp(youtubedl-android)를 감싼 다운로드 엔진.
 * 서버 없이 폰 안에서 인스타그램 링크를 받아 갤러리(Movies/InstaSaver)에 저장한다.
 */
object Engine {
    private const val ALBUM = "InstaSaver"
    private const val UPDATE_INTERVAL_MS = 24 * 60 * 60 * 1000L

    private val initLock = Mutex()
    private var initialized = false

    /** 처음 한 번 파이썬·ffmpeg 를 풀어 놓는다 (첫 실행에 몇 초 걸린다) */
    suspend fun ensureInit(context: Context) = initLock.withLock {
        if (initialized) return@withLock
        withContext(Dispatchers.IO) {
            val app = context.applicationContext
            YoutubeDL.getInstance().init(app)
            FFmpeg.getInstance().init(app)
        }
        initialized = true
    }

    /**
     * 인스타그램이 구조를 자주 바꾸므로 yt-dlp 를 하루 한 번 최신으로 올린다.
     * force 가 true 면 시간과 관계없이 바로 업데이트한다.
     */
    suspend fun updateIfNeeded(context: Context, force: Boolean = false): String? {
        val prefs = context.getSharedPreferences("engine", Context.MODE_PRIVATE)
        val last = prefs.getLong("last_update", 0)
        if (!force && System.currentTimeMillis() - last < UPDATE_INTERVAL_MS) return null
        ensureInit(context)
        return withContext(Dispatchers.IO) {
            val status = YoutubeDL.getInstance()
                .updateYoutubeDL(context.applicationContext, YoutubeDL.UpdateChannel.STABLE)
            prefs.edit().putLong("last_update", System.currentTimeMillis()).apply()
            status?.name
        }
    }

    fun version(context: Context): String? =
        YoutubeDL.getInstance().version(context.applicationContext)

    fun cancel(processId: String) {
        YoutubeDL.getInstance().destroyProcessById(processId)
    }

    /**
     * 링크의 동영상(여러 장 게시물이면 모두)을 받아 갤러리에 저장한다.
     * onProgress 는 0~100 진행률과 yt-dlp 출력 한 줄을 받는다.
     */
    suspend fun download(
        context: Context,
        url: String,
        processId: String,
        onProgress: (Float, String) -> Unit,
    ): List<SavedMedia> {
        ensureInit(context)
        val workDir = File(context.cacheDir, "dl/$processId").apply { mkdirs() }
        try {
            withContext(Dispatchers.IO) {
                val request = YoutubeDLRequest(url).apply {
                    addOption("-o", "${workDir.absolutePath}/%(uploader_id|instagram)s_%(id)s.%(ext)s")
                    // 최고화질 영상+음성을 ffmpeg 로 합쳐 mp4 로 만든다
                    addOption("-f", "bv*+ba/b")
                    addOption("--merge-output-format", "mp4")
                    addOption("--yes-playlist")
                    addOption("--no-mtime")
                    Session.cookieFile(context)?.let { addOption("--cookies", it.absolutePath) }
                }
                YoutubeDL.getInstance().execute(request, processId) { progress, _, line ->
                    onProgress(progress, line)
                }
            }
            val files = workDir.listFiles()
                ?.filter { it.isFile && !it.name.endsWith(".part") && !it.name.endsWith(".ytdl") }
                .orEmpty()
                .sortedBy { it.name }
            return withContext(Dispatchers.IO) { files.map { saveToGallery(context, it) } }
        } finally {
            workDir.deleteRecursively()
        }
    }

    private fun saveToGallery(context: Context, file: File): SavedMedia {
        val isImage = file.extension.lowercase() in setOf("jpg", "jpeg", "png", "webp")
        val mime = when {
            isImage -> "image/" + file.extension.lowercase().replace("jpg", "jpeg")
            else -> "video/mp4"
        }
        val collection = if (isImage) {
            MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        } else {
            MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        }
        val dir = if (isImage) Environment.DIRECTORY_PICTURES else Environment.DIRECTORY_MOVIES
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, file.name)
            put(MediaStore.MediaColumns.MIME_TYPE, mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, "$dir/$ALBUM")
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val resolver = context.contentResolver
        val uri = resolver.insert(collection, values) ?: error("갤러리에 저장하지 못했습니다.")
        try {
            resolver.openOutputStream(uri)!!.use { out -> file.inputStream().use { it.copyTo(out) } }
            values.clear()
            values.put(MediaStore.MediaColumns.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
        } catch (e: Exception) {
            resolver.delete(uri, null, null)
            throw e
        }
        return SavedMedia(uri, file.name, mime)
    }
}
