package kr.instasaver

import android.net.Uri

object Links {
    private val INSTA_URL = Regex("""https?://(?:www\.|m\.)?(?:instagram\.com|instagr\.am)/\S+""")

    /** 공유된 텍스트에서 인스타그램 링크만 뽑고 추적용 쿼리(?igsh=...)를 지운다 */
    fun extract(text: CharSequence?): String? {
        val match = INSTA_URL.find(text ?: return null) ?: return null
        val uri = Uri.parse(match.value.trimEnd(')', '.', ','))
        val path = uri.path?.takeIf { it.length > 1 } ?: return null
        return "https://www.instagram.com$path"
    }
}
