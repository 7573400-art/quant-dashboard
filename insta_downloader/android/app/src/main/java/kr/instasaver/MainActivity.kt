package kr.instasaver

import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Bitmap
import android.os.Bundle
import android.util.Size
import android.view.LayoutInflater
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.progressindicator.LinearProgressIndicator
import com.google.android.material.textfield.TextInputEditText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    private val vm: MainViewModel by viewModels()

    private lateinit var toolbar: MaterialToolbar
    private lateinit var input: TextInputEditText
    private lateinit var downloadButton: Button
    private lateinit var progress: LinearProgressIndicator
    private lateinit var status: TextView
    private lateinit var results: LinearLayout
    private var shownResults: List<SavedMedia> = emptyList()

    private val login = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        updateMenu()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        toolbar = findViewById(R.id.toolbar)
        input = findViewById(R.id.url_input)
        downloadButton = findViewById(R.id.download_button)
        progress = findViewById(R.id.progress)
        status = findViewById(R.id.status)
        results = findViewById(R.id.results)

        toolbar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_login -> login.launch(Intent(this, LoginActivity::class.java))
                R.id.action_logout -> {
                    Session.logout(this)
                    Toast.makeText(this, R.string.logout_done, Toast.LENGTH_SHORT).show()
                    updateMenu()
                }
                R.id.action_update -> vm.updateEngine()
            }
            true
        }
        updateMenu()

        findViewById<Button>(R.id.paste_button).setOnClickListener {
            val link = clipboardLink()
            if (link == null) {
                Toast.makeText(this, R.string.no_link_in_clipboard, Toast.LENGTH_SHORT).show()
            } else {
                input.setText(link)
                startDownload()
            }
        }
        downloadButton.setOnClickListener {
            if (vm.state.value.busy) vm.cancel() else startDownload()
        }
        input.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_GO) startDownload()
            true
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                vm.state.collect(::render)
            }
        }

        if (savedInstanceState == null) handleShare(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleShare(intent)
    }

    /** 인스타그램 앱에서 '공유 → 인스타저장'으로 들어오면 바로 다운로드한다 */
    private fun handleShare(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND) return
        val link = Links.extract(intent.getStringExtra(Intent.EXTRA_TEXT))
        if (link == null) {
            Toast.makeText(this, R.string.err_invalid_link, Toast.LENGTH_SHORT).show()
            return
        }
        input.setText(link)
        startDownload()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        // 안드로이드 10+ 는 화면에 포커스가 있을 때만 클립보드를 읽을 수 있다
        if (hasFocus && input.text.isNullOrBlank() && !vm.state.value.busy) {
            clipboardLink()?.let { input.setText(it) }
        }
    }

    private fun clipboardLink(): String? {
        val clip = getSystemService(ClipboardManager::class.java)?.primaryClip ?: return null
        if (clip.itemCount == 0) return null
        return Links.extract(clip.getItemAt(0).coerceToText(this))
    }

    private fun startDownload() {
        val link = Links.extract(input.text)
        if (link == null) {
            Toast.makeText(this, R.string.err_invalid_link, Toast.LENGTH_SHORT).show()
            return
        }
        input.setText(link)
        vm.download(link)
    }

    private fun updateMenu() {
        val loggedIn = Session.isLoggedIn(this)
        toolbar.menu.findItem(R.id.action_login).isVisible = !loggedIn
        toolbar.menu.findItem(R.id.action_logout).isVisible = loggedIn
    }

    private fun render(state: UiState) {
        downloadButton.setText(if (state.busy) R.string.cancel else R.string.download)
        input.isEnabled = !state.busy
        progress.visibility = if (state.busy) View.VISIBLE else View.GONE
        progress.isIndeterminate = state.progress <= 0f
        if (state.progress > 0f) progress.setProgressCompat(state.progress.toInt(), true)
        status.text = state.status
        status.setTextColor(
            getColor(if (state.error) R.color.error else R.color.text_secondary)
        )
        if (state.results != shownResults) {
            shownResults = state.results
            renderResults(state.results)
        }
    }

    private fun renderResults(items: List<SavedMedia>) {
        results.removeAllViews()
        val inflater = LayoutInflater.from(this)
        for (item in items) {
            val row = inflater.inflate(R.layout.item_result, results, false)
            row.findViewById<TextView>(R.id.name).text = item.name
            val thumb = row.findViewById<ImageView>(R.id.thumb)
            lifecycleScope.launch {
                val bmp: Bitmap? = withContext(Dispatchers.IO) {
                    runCatching { contentResolver.loadThumbnail(item.uri, Size(240, 240), null) }.getOrNull()
                }
                bmp?.let(thumb::setImageBitmap)
            }
            row.findViewById<Button>(R.id.open).setOnClickListener {
                startActivity(
                    Intent(Intent.ACTION_VIEW).setDataAndType(item.uri, item.mime)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                )
            }
            row.findViewById<Button>(R.id.share).setOnClickListener {
                val send = Intent(Intent.ACTION_SEND).setType(item.mime)
                    .putExtra(Intent.EXTRA_STREAM, item.uri)
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                startActivity(Intent.createChooser(send, getString(R.string.share)))
            }
            results.addView(row)
        }
    }
}
