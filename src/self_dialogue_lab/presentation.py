"""Local nature imagery and page framing; no business state or network access."""

from base64 import b64encode
from functools import lru_cache
from html import escape
from pathlib import Path

ASSETS = Path(__file__).parent / 'assets'

PAGES = {
    '対話': (
        '01 / DIALOGUE', '考えを、もう一歩深く。',
        '少し立ち止まり、自分の言葉に耳を澄ます。',
        ('シナリオを選ぶ', '例文や入力で試す', '残したい言葉を確認する'),
    ),
    '考えの一覧': (
        '02 / YOUR THOUGHTS', '変わっていく考えも、そのまま。',
        'いまの考えと、そこに至った道のりを残す。',
        ('考えを書き留める', '理由と文脈を添える', '変化を新しい記録にする'),
    ),
    '保存確認': (
        '03 / REVIEW', '残す言葉は、自分で決める。',
        '急いで決めず、ひとつずつ、自分の言葉を確かめる。',
        ('根拠の発言を読む', '必要なら候補を整える', '承認するか、拒否する'),
    ),
}


@lru_cache(maxsize=1)
def nature_stylesheet():
    photo = b64encode((ASSETS / 'lake-dawn.png').read_bytes()).decode('ascii')
    css = (ASSETS / 'nature.css').read_text(encoding='utf-8')
    return '<style>' + css.replace('__LANDSCAPE__', 'data:image/png;base64,' + photo) + '</style>'


def page_hero(page):
    kicker, title, subtitle, _ = PAGES[page]
    return (
        '<section class="nature-hero" aria-label="' + escape(title, quote=True) + '">'
        '<div class="nature-hero-content"><p class="nature-kicker">SELF DIALOGUE LAB · ' + escape(kicker) + '</p>'
        '<h1>' + escape(title) + '</h1><p class="nature-subtitle">' + escape(subtitle) + '</p>'
        '<span class="nature-note">自分の言葉から、次の問いへ</span></div></section>'
        '<p class="nature-photo-credit">朝霧の湖と森をモチーフにしたAI生成の風景</p>'
    )


def page_steps(page, gemini=False):
    labels = ('話題を話す', '返答を一緒に考える', '残したい言葉だけ保存する') if page == '対話' and gemini else PAGES[page][3]
    steps = ''.join(
        '<li><span class="nature-step-number">' + str(index) + '</span><span>' + escape(text) + '</span></li>'
        for index, text in enumerate(labels, start=1)
    )
    return '<ol class="nature-steps" aria-label="この画面の操作手順">' + steps + '</ol>'
