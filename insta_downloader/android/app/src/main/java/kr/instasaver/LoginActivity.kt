package kr.instasaver

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

/** 인스타그램 웹 로그인 화면. 로그인이 끝나면 쿠키를 저장하고 닫힌다. */
class LoginActivity : AppCompatActivity() {

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val web = WebView(this)
        web.fitsSystemWindows = true
        setContentView(web)

        CookieManager.getInstance().setAcceptCookie(true)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, url: String) {
                CookieManager.getInstance().flush()
                if (Session.saveFromWebView(this@LoginActivity)) {
                    Toast.makeText(this@LoginActivity, R.string.login_done, Toast.LENGTH_SHORT).show()
                    setResult(RESULT_OK)
                    finish()
                }
            }
        }
        web.loadUrl("https://www.instagram.com/accounts/login/")
    }
}
