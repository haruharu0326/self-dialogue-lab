from dataclasses import dataclass
from typing import Protocol


@dataclass
class Reply:
    interpretation: str
    question: str
    references: list[dict]


class ResponderError(RuntimeError):
    """Only safe, user-facing messages; the exchange is not saved."""


class Responder(Protocol):
    """通常経路へ注入する応答器の契約。失敗は安全な固定文言だけを持つResponderError等で通知する。
    詳細はdocs/design/internal-design.mdの「応答器の契約」。"""
    provider: str
    model: str

    def respond(self, message: str, scenario: str, records: list[dict], *, correction_of: dict | None = None,
                change_from: dict | None = None, history: list[dict] | None = None, demo: bool = False,
                tone_context: dict | None = None) -> Reply: ...


class MockResponder:
    provider = 'mock'
    model = 'mock-fixed'

    # history・demo・tone_contextは契約上受け取るが、固定応答では使わない。
    def respond(self, message, scenario, records, *, correction_of=None, change_from=None, history=None, demo=False, tone_context=None):
        if change_from is not None:
            return Reply('考えが変わったという本人の申告を受け取りました。誤入力の修正とは区別し、以前の記録を残す保存候補を作成しました。まだ長期記録には保存していません。',
                         '保存確認で、新しい考え・変わった理由・文脈を確認して承認してください。', [change_from])
        if correction_of is not None:
            return Reply(
                '先ほどの解釈を取り下げます。訂正内容は「' + message.strip() + '」と受け止めました。これは本人の発言の引用であり、新しい推測は加えていません。',
                'この受け止め方で合っていますか？ 訂正された観点から、もう少し整理したい点はありますか？', [])
        # シナリオDは検索結果0件を再現する固定モック。実際の意味検索ではない。
        if scenario == 'D. 関連記録がないときに質問する':
            return self.without_evidence()
        if scenario == 'E. 保存候補を承認または拒否する':
            return Reply('本人の発言をそのまま保存候補にしました。まだ長期記録には保存していません。',
                         'この内容を残しますか？ 「保存確認」で根拠の発言と候補を確認し、必要なら編集して承認するか、拒否してください。', [])
        # 長期記録だけを受け取り、変更前の記録は自動参照から除く。
        superseded = {r['previous_id'] for r in records if r['previous_id']}
        active = [r for r in records if r['id'] not in superseded and not r.get('superseded', 0)]
        relevant = [r for r in active if any(w in r['thought'] for w in ('裁量', '安定'))][:2]
        if scenario == 'B. AIの解釈を訂正する':
            refs = [r for r in active if '収入の安定' in r['thought']][:1]
            if not refs:
                return self.without_evidence()
            return Reply('これは訂正を試すための固定の解釈例です。選択した記録「' + refs[0]['thought'] + '」を使い、収入への不安が迷いの中心かもしれない、という解釈例を表示しています。入力の意味を理解した結果ではありません。',
                         'この解釈は合っていますか？ 違う場合は下の「解釈を訂正する」から、実際に気になっていることを教えてください。',
                         refs)
        if not relevant:
            return self.without_evidence()
        return Reply('これは固定の問い返しです。下の記録を文字列条件で選んでいます。入力の意味を理解した結果ではなく、今の優先順位は判断していません。',
                     '過去にはこのように記録しています。今回も同じ優先順位でしょうか？ 挑戦するために必要な安心の条件は何ですか？', relevant)


    @staticmethod
    def without_evidence():
        return Reply('この話題に関連する記録は見つかりませんでした。今ある記録だけでは、あなたの考えや大切にしていることは分かりません。',
                     'この話題について、今どのように考えていますか？ まだ考えがまとまっていなければ、気になっている点から教えてください。', [])
