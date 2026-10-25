package kr.instasaver

import android.content.Context
import android.webkit.CookieManager
import java.io.File

/**
 * 인스타그램 로그인 쿠키를 yt-dlp 가 읽는 Netscape 쿠키 파일로 보관한다.
 * 비공개 계정이나 로그인을 요구하는 게시물을 받을 때 쓰인다. 파일은 앱 내부 저장소에만 있다.
 */
object Session {
    private const val INSTAGRAM = "https://www.instagram.com"
    private const val ONE_YEAR_SEC = 365L * 24 * 60 * 60

    private fun file(context: Context) = File(context.filesDir, "instagram_cookies.txt")

    fun cookieFile(context: Context): File? = file(context).takeIf { it.exists() }

    fun isLoggedIn(context: Context) = cookieFile(context) != null

    /** WebView 에 로그인된 쿠키가 있으면 파일로 저장하고 true 를 돌려준다 */
    fun saveFromWebView(context: Context): Boolean {
        val raw = CookieManager.getInstance().getCookie(INSTAGRAM) ?: return false
        val cookies = raw.split(";").mapNotNull { part ->
            val idx = part.indexOf('=')
            if (idx <= 0) null else part.substring(0, idx).trim() to part.substring(idx + 1).trim()
        }
        if (cookies.none { it.first == "sessionid" && it.second.isNotEmpty() }) return false

        val expiry = System.currentTimeMillis() / 1000 + ONE_YEAR_SEC
        val text = buildString {
            appendLine("# Netscape HTTP Cookie File")
            for ((name, value) in cookies) {
                appendLine(listOf(".instagram.com", "TRUE", "/", "TRUE", expiry, name, value).joinToString("\t"))
            }
        }
        file(context).writeText(text)
        return true
    }

    fun logout(context: Context) {
        file(context).delete()
        CookieManager.getInstance().removeAllCookies(null)
        CookieManager.getInstance().flush()
    }
}
