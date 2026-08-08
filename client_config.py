# クライアント情報収集 — 対象クライアント定義
# name_keywords         : 会社名バリエーション（Google News検索・ノイズ除去フィルタに使用）
# industry_keywords      : コア事業関連キーワード（AIプロンプトの文脈補助に使用）
# ir_rss                 : IR/ニュースページの公式RSSフィード（ある場合）
# news_list_url          : 公式RSSがない場合の代替。ニュース一覧ページをスクレイピングする

CLIENTS = [
    {
        "key": "ushio",
        "name": "ウシオ電機",
        "core_business": "半導体製造装置、光源、産業用光技術",
        "name_keywords": ["ウシオ電機", "USHIO", "Ushio Inc"],
        "industry_keywords": [
            "半導体製造装置", "semiconductor equipment", "露光装置", "lithography",
            "光源", "light source", "ランプ", "産業用光技術", "industrial light technology",
            "UV", "EUV", "LED光源",
        ],
        "ir_url": "https://www.ushio.co.jp/jp/ir/",
        "ir_rss": "https://www.ushio.co.jp/jp/news/1004.xml",
        "news_list_url": None,
    },
    {
        "key": "en_japan",
        "name": "エン株式会社",
        "core_business": "採用、人材派遣、HR Tech、求人",
        "name_keywords": ["エン・ジャパン", "エン株式会社", "en Japan", "engage"],
        "industry_keywords": [
            "採用", "recruitment", "人材派遣", "staffing", "HR Tech", "求人",
            "転職", "job market", "labor market", "人材紹介",
        ],
        "ir_url": "https://corp.en-japan.com/ir/",
        "ir_rss": "https://corp.en-japan.com/IR/ir.xml",
        "news_list_url": None,
    },
    {
        "key": "kyorin",
        "name": "杏林製薬",
        "core_business": "創薬、新薬開発、製薬、臨床試験",
        "name_keywords": ["杏林製薬", "Kyorin Pharmaceutical", "Kyorin Pharma"],
        "industry_keywords": [
            "創薬", "drug discovery", "新薬開発", "new drug development",
            "製薬", "pharmaceutical", "臨床試験", "clinical trial", "治験",
        ],
        "ir_url": "https://www.kyorin-pharm.co.jp/ir/",
        "ir_rss": None,
        "news_list_url": "https://www.kyorin-pharm.co.jp/news/",
    },
    {
        "key": "are_holdings",
        "name": "AREホールディングス",
        "core_business": "金精錬、貴金属、リサイクル、金",
        "name_keywords": [
            "AREホールディングス", "ARE Holdings", "アサヒプリテック", "アサヒメタルファイン",
        ],
        "industry_keywords": [
            "金精錬", "gold refining", "貴金属", "precious metal", "precious metals recycling",
            "貴金属リサイクル", "recycling", "金地金", "gold bullion", "銀地金", "プラチナ", "platinum",
            "パラジウム", "palladium",
        ],
        # 実際のドメインは are-holdings.com（ご指定の are-holdings.jp はDNS解決不可のため修正）
        "ir_url": "https://www.are-holdings.com/ir/",
        "ir_rss": None,
        "news_list_url": "https://www.are-holdings.com/ir/news/",
    },
]
