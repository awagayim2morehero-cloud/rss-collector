# 近未来監査プロフェッション研究会
# 素材検討表 検索命題定義
# アーキテクト作成 2026年6月

# 既採用記事（タイトル部分一致で除外）
EXCLUDED_TITLES = [
    "Cognizant ServiceNow",
    "KPMG Singapore AI Governance Playbook",
    "Stanford 2026 AI Index",
    "EY新日本生成AI基盤",
    "DataSnipper AI活用ステージ",
    "KPMG IIA Singapore",
]

ADDITIONAL_SEARCH_QUERIES = [

    # ── 命題群1：第3回補強 — 領域② 成長・マーケット ──────────────────────

    {
        "session": 3,
        "label": "3-1: 監査法人ビジネスモデル変容",
        "theme": "AI時代における監査法人のビジネスモデル変容と収益構造の転換",
        "keywords": [
            "audit firm business model transformation AI 2025 2026",
            "audit firm revenue shift advisory assurance AI",
            "Big4 new service lines AI governance revenue 2026",
            "監査法人 ビジネスモデル 変革 AI 新サービス",
        ],
        "intent": (
            "「監査という業務の収益構造がAIによってどう変わるか」を示す素材を探す。"
            "単なるAI導入事例ではなく、収益モデル・サービス設計・顧客関係の"
            "構造的変化を論じた記事を優先する。"
            "Big4の事業戦略転換・新サービスライン開設・監査以外への拡張が"
            "確認できるものは★★★とする。"
        ),
        "priority": "★★★",
        "tag": "②",
    },

    {
        "session": 3,
        "label": "3-2: 大手優位性の持続可能性",
        "theme": "AI時代における大手監査法人の競争優位は持続するか",
        "keywords": [
            "Big4 competitive advantage AI disruption audit market 2026",
            "audit market concentration AI smaller firms technology",
            "audit firm differentiation AI commoditization",
            "監査法人 競争優位 AI 中小 格差 持続可能性",
        ],
        "intent": (
            "「AIが参入障壁を下げ大手優位が崩れるか、逆に強化されるか」という"
            "問いに答える素材を探す。"
            "「大手だからAIに強い」「AIで中小が台頭する」どちらの論点も歓迎。"
            "参加者の「自法人の将来」への問いに直接刺さる素材を優先する。"
        ),
        "priority": "★★★",
        "tag": "②",
    },

    {
        "session": 3,
        "label": "3-3: AIガバナンス保証の市場規模と担い手",
        "theme": "AIガバナンス保証サービスの市場規模・担い手・監査法人の参入機会",
        "keywords": [
            "AI governance assurance market size 2026 audit",
            "third party AI audit market opportunity",
            "ISO 42001 certification market audit firm",
            "EU AI Act compliance assurance provider 2026",
            "AIガバナンス 第三者保証 市場規模 監査法人",
        ],
        "intent": (
            "AIガバナンス保証を「新業務領域」として論じる素材を探す。"
            "特に「誰がその担い手になっているか（ITベンダー・コンサル・監査法人）」"
            "「市場規模の予測」「参入に必要な要件」が含まれる記事を優先する。"
            "既採用のCognizant×ServiceNow・KPMGプレイブックと重複しない新情報を求める。"
        ),
        "priority": "★★",
        "tag": "②③",
    },

    # ── 命題群2：第4回補強 — 領域③ 監査人の役割 ──────────────────────────

    {
        "session": 4,
        "label": "4-1: Advice/Insight/Foresightへの役割転換",
        "theme": "AIが保証業務を代替するとき、監査人はAdvice・Insight・Foresightの提供者に転換できるか",
        "keywords": [
            "auditor role transformation advice insight foresight AI 2026",
            "internal audit value beyond assurance AI era",
            "IIA auditor competency future skills 2025 2026",
            "audit professional judgment AI replacement",
            "監査人 役割 転換 アドバイス 洞察 AI 将来",
        ],
        "intent": (
            "IIAが示す「Assurance→Advice→Insight→Foresight」という役割転換の"
            "具体像を示す素材を探す。"
            "「AIが保証業務を担う時代に、監査人は何で差異化するか」という"
            "適応課題の次元で論じた記事を優先する。"
            "スキル論・資格論の次元にとどまるものは優先度を下げる。"
        ),
        "priority": "★★★",
        "tag": "③",
    },

    {
        "session": 4,
        "label": "4-2: プロフェッショナルジャッジメントの境界",
        "theme": "AIが判断を支援・代替するとき、監査人の職業的判断の境界はどこにあるか",
        "keywords": [
            "professional judgment auditor AI boundary human oversight",
            "auditor skepticism AI automation cognitive bias",
            "PCAOB IAASB human judgment AI audit standards 2026",
            "audit responsibility AI generated output accountability",
            "職業的判断 監査人 AI 境界 注意義務",
        ],
        "intent": (
            "「AIが判断を出したとき、監査人は何を判断するのか」という"
            "適応課題の核心に触れる素材を探す。"
            "基準設定機関（PCAOB・IAASB）の動向・判例・事故事例を含むものを優先。"
            "「AIの出力をそのまま使うことの責任」という問いに答える素材が理想。"
        ),
        "priority": "★★★",
        "tag": "①③",
    },

    {
        "session": 4,
        "label": "4-3: 技術的問題と適応課題の分類事例",
        "theme": "監査現場でAIが解決できる技術的問題と、人間が向き合うべき適応課題の具体的分類",
        "keywords": [
            "adaptive challenge technical problem audit AI implementation",
            "what AI cannot do audit human role irreplaceable",
            "audit firm AI limits judgment ethics relationship",
            "エージェンティックAI 監査 人間の役割 適応課題",
        ],
        "intent": (
            "ハイフェッツの「技術的問題（AIが解ける）」vs「適応課題（AIが解けない）」"
            "という枠組みを監査実務に当てはめる素材を探す。"
            "「AIには任せられないこと」を具体的に論じた記事が最適。"
            "「AIで効率化できること」の記事は技術的問題として参考素材扱いとする。"
        ),
        "priority": "★★",
        "tag": "③④",
    },

    # ── 命題群3：第5回補強 — 領域④ 人財 ─────────────────────────────────

    {
        "session": 5,
        "label": "5-1: 監査法人のスキルセット転換",
        "theme": "AI時代に監査法人が求めるスキルセットはどう変わるか。育成の梯子の再設計",
        "keywords": [
            "audit firm talent skill shift AI 2025 2026",
            "auditor reskilling upskilling AI data analytics",
            "IIA competency framework 2025 future auditor skills",
            "EY audit data strategist talent transformation",
            "監査法人 人材育成 スキル転換 AI データアナリスト",
        ],
        "intent": (
            "「AIリテラシーをベースにした高度専門判断」という新スキルモデルの"
            "具体像を示す素材を探す。"
            "IIA能力フレームワーク2025年版・EY「監査データストラテジスト」等の"
            "具体的プログラムを論じた記事を優先。"
            "「スキルを身につける」という個人論だけでなく"
            "「組織がどう育てるか」という法人論の素材も求める。"
        ),
        "priority": "★★★",
        "tag": "④",
    },

    {
        "session": 5,
        "label": "5-2: AI時代の採用・人材獲得戦略",
        "theme": "AIスキルを持つ人材の獲得競争と監査法人の人材戦略",
        "keywords": [
            "audit firm hiring AI talent competition tech sector 2026",
            "accounting firm attract retain AI skilled professionals",
            "audit profession talent shortage AI era next generation",
            "監査法人 採用 AI人材 競争 テック企業 離職",
        ],
        "intent": (
            "「AIによってスキル要件が変わる中、誰を採用し・誰が来てくれるか」"
            "という人財戦略の問いに答える素材を探す。"
            "特に「テック系人材との競合」「若者の監査法人離れ」"
            "「AI時代の監査職の魅力」を論じた記事が理想。"
            "グリーンリーフ的な「誰のために育てるか」という問いへの橋渡しになる素材を優先。"
        ),
        "priority": "★★",
        "tag": "④",
    },

    {
        "session": 5,
        "label": "5-3: 組織として問いを立てる力の育成",
        "theme": "「深く考える力」「問いを立てる力」を組織として育てることの設計",
        "keywords": [
            "audit firm culture critical thinking psychological safety talent",
            "developing judgment skepticism next generation auditors AI",
            "learning organization audit innovation culture",
            "監査法人 組織文化 育成 問いを立てる力 懐疑心 評価制度",
        ],
        "intent": (
            "エドモンドソン→グリーンリーフの論理的連鎖を人財育成で示す素材を探す。"
            "「心理的安全性のある組織がどう人を育てるか」"
            "「AIバイアスに抵抗できる判断力をどう育てるか」を論じた記事が最適。"
            "人事制度・評価設計への言及があるものを優先する。"
        ),
        "priority": "★★",
        "tag": "①④",
    },

    # ── 命題群4：第3〜4回クロス補強 — 領域②③ ──────────────────────────

    {
        "session": "3-4",
        "label": "34-1: 価値観と新領域参入の葛藤",
        "theme": "監査人・監査法人がAI新業務領域に参入するとき直面する価値観上の葛藤",
        "keywords": [
            "auditor independence objectivity AI advisory conflict",
            "audit firm non-audit services AI governance tension",
            "professional identity auditor transformation AI resistance",
            "監査人 独立性 AI コンサルティング 価値観 葛藤",
        ],
        "intent": (
            "「独立性・懐疑心を守りながら、新業務領域でアドバイスを提供する」"
            "という役割の二重性・葛藤を論じた素材を探す。"
            "ジョージ的な「自分の価値観を持ち続けながら変化に適応する」"
            "という問いに接続できる記事が理想。"
            "「独立性を捨てて新領域に入る」vs「独立性を守り旧来業務に残る」"
            "という二項対立を超えた論点を提供するものを優先。"
        ),
        "priority": "★★",
        "tag": "②③",
    },

    # ── 命題群5：第2回B型設問補強 — 領域① ────────────────────────────────

    {
        "session": 2,
        "label": "2-1: AI監査ミス・エラー事例",
        "theme": "AI活用監査における実際のエラー・ミス・問題発生事例",
        "keywords": [
            "AI audit error hallucination accounting 2025 2026",
            "generative AI mistake financial audit real case",
            "AI generated audit workpaper error quality issue",
            "AIハルシネーション 監査 調書 誤り 事例",
        ],
        "intent": (
            "「AIが間違えた」「AIを信じた結果どうなったか」という"
            "具体的事例・インシデントを探す。"
            "B型設問「あなたのチームでAIが出した答えに違和感を覚えたことはあるか」"
            "を引き出す素材として機能するものが理想。"
            "架空・仮定事例ではなく実際の報告・開示・訴訟事例を優先する。"
        ),
        "priority": "★★",
        "tag": "①",
    },

    {
        "session": 2,
        "label": "2-2: 自動化バイアスの実証研究",
        "theme": "「AIを信じすぎる」自動化バイアスの実証研究・心理実験・事例",
        "keywords": [
            "automation bias auditor research study evidence 2025",
            "over-reliance AI decision making professional judgment",
            "automation complacency financial professional experiment",
            "自動化バイアス 監査人 過信 実証研究 心理",
        ],
        "intent": (
            "エドモンドソン理論を「自動化バイアス」という監査実務の問題に"
            "接続するための実証的素材を探す。"
            "「人間はなぜAIを信じすぎるのか」というメカニズムを論じた"
            "行動科学・認知科学的アプローチの記事も歓迎。"
            "設問「今のあなたのチームで、AIが出した結果に誰も異議を唱えなかった"
            "場面があるとしたら、それはなぜか」に接続できる素材を優先。"
        ),
        "priority": "★★",
        "tag": "①",
    },
]

# 実行順序（素材不足セッションを優先）
SESSION_EXECUTION_ORDER = [5, 4, 3, "3-4", 2]
