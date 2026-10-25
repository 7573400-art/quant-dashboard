package kr.instasaver

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.yausername.youtubedl_android.YoutubeDL
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID

data class UiState(
    val busy: Boolean = false,
    val progress: Float = -1f,
    val status: String = "",
    val error: Boolean = false,
    val results: List<SavedMedia> = emptyList(),
)

/** 화면을 돌려도 다운로드가 끊기지 않도록 작업은 뷰모델에서 돌린다 */
class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state

    private var job: Job? = null
    private var processId: String? = null

    init {
        // 앱을 켜면 엔진을 미리 준비하고, 하루 한 번 yt-dlp 를 최신으로 올린다
        viewModelScope.launch {
            runCatching {
                Engine.ensureInit(app)
                Engine.updateIfNeeded(app)
            }
        }
    }

    fun download(url: String) {
        if (_state.value.busy) return
        val app = getApplication<Application>()
        val id = UUID.randomUUID().toString()
        processId = id
        _state.update { it.copy(busy = true, progress = -1f, status = app.getString(R.string.status_preparing), error = false) }

        job = viewModelScope.launch {
            try {
                val saved = Engine.download(app, url, id) { progress, _ ->
                    _state.update { it.copy(progress = progress, status = app.getString(R.string.status_downloading, progress.toInt().coerceAtLeast(0))) }
                }
                _state.update {
                    it.copy(
                        busy = false,
                        status = app.getString(R.string.status_saved, saved.size),
                        results = saved + it.results,
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: YoutubeDL.CanceledException) {
                _state.update { it.copy(busy = false, status = app.getString(R.string.status_canceled)) }
            } catch (e: Exception) {
                _state.update { it.copy(busy = false, status = friendlyError(e), error = true) }
            }
        }
    }

    fun cancel() {
        processId?.let(Engine::cancel)
        job?.cancel()
        _state.update { it.copy(busy = false, status = getApplication<Application>().getString(R.string.status_canceled)) }
    }

    fun updateEngine() {
        if (_state.value.busy) return
        val app = getApplication<Application>()
        _state.update { it.copy(busy = true, progress = -1f, status = app.getString(R.string.status_updating), error = false) }
        viewModelScope.launch {
            try {
                Engine.updateIfNeeded(app, force = true)
                _state.update { it.copy(busy = false, status = app.getString(R.string.status_updated, Engine.version(app) ?: "")) }
            } catch (e: Exception) {
                _state.update { it.copy(busy = false, status = app.getString(R.string.err_update), error = true) }
            }
        }
    }

    private fun friendlyError(e: Exception): String {
        val app = getApplication<Application>()
        val msg = e.message.orEmpty().lowercase()
        return app.getString(
            when {
                "login" in msg || "cookies" in msg || "rate" in msg ->
                    if (Session.isLoggedIn(app)) R.string.err_login_expired else R.string.err_login_required
                "no video" in msg -> R.string.err_no_video
                "unable to download" in msg || "network" in msg || "resolve" in msg -> R.string.err_network
                else -> R.string.err_generic
            }
        )
    }
}
