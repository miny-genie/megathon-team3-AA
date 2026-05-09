"""트렌드 분석, 감성 개요, 매체 반응 분석 모듈."""

STOPWORDS = {'기자','뉴스','보도','관련','대한','통해','위해','것으로','에서','으로','이번','올해','지난','한다','있다','했다','된다','하는','라고','라며'}


def _extract_words(article):
    """기사에서 키워드 후보 추출."""
    parts = []
    for field in ('title', 'snippet', 'opportunity_type'):
        v = article.get(field, '') or ''
        parts.extend(v.split())
    matched = article.get('matched_keywords', []) or []
    if isinstance(matched, list):
        parts.extend(matched)
    return [w for w in parts if len(w) >= 2 and w not in STOPWORDS]


def _norm(values):
    """0-100 정규화."""
    if not values:
        return []
    mx = max(values)
    mn = min(values)
    if mx == mn:
        return [50.0] * len(values)
    return [(v - mn) / (mx - mn) * 100 for v in values]


def extract_trend_keywords(articles, top_n=10):
    """키워드 트렌드 추출."""
    if not articles:
        return []

    kw_data = {}  # keyword -> list of articles
    for a in articles:
        words = _extract_words(a)
        seen = set()
        for w in words:
            if w not in seen:
                seen.add(w)
                kw_data.setdefault(w, []).append(a)

    stats = []
    for kw, arts in kw_data.items():
        freq = len(arts)
        scores = [a.get('final_score_100', 0) or 0 for a in arts]
        match_scores = [a.get('role_keyword_match_score', 0) or 0 for a in arts]
        sources = set(a.get('source_id', '') for a in arts)
        sentiments = [a.get('sentiment', 'neutral') for a in arts]
        pos = sentiments.count('positive')
        neu = sentiments.count('neutral')
        neg = sentiments.count('negative')
        neg_ratio = neg / freq if freq else 0
        stats.append({
            'keyword': kw,
            'freq': freq,
            'avg_score': sum(scores) / freq,
            'avg_match': sum(match_scores) / freq,
            'source_count': len(sources),
            'neg_ratio': neg_ratio,
            'pos': pos, 'neu': neu, 'neg': neg,
            'articles': arts,
        })

    if not stats:
        return []

    freqs_norm = _norm([s['freq'] for s in stats])
    scores_norm = _norm([s['avg_score'] for s in stats])
    match_norm = _norm([s['avg_match'] for s in stats])
    source_norm = _norm([s['source_count'] for s in stats])

    results = []
    for i, s in enumerate(stats):
        trend_score = (
            freqs_norm[i] * 0.30 +
            scores_norm[i] * 0.30 +
            match_norm[i] * 0.20 +
            source_norm[i] * 0.10 +
            s['neg_ratio'] * 100 * 0.10
        )
        importance_vals = [a.get('importance', 0) or 0 for a in s['articles']]
        results.append({
            'trend_keyword': s['keyword'],
            'trend_score': round(trend_score, 2),
            'article_count': s['freq'],
            'avg_importance': round(sum(importance_vals) / len(importance_vals), 2) if importance_vals else 0,
            'avg_final_score': round(s['avg_score'], 2),
            'avg_role_keyword_match_score': round(s['avg_match'], 2),
            'positive_count': s['pos'],
            'neutral_count': s['neu'],
            'negative_count': s['neg'],
            'negative_ratio': round(s['neg_ratio'], 4),
            'unique_sources': s['source_count'],
        })

    results.sort(key=lambda x: x['trend_score'], reverse=True)
    return results[:top_n]


def calculate_sentiment_overview(articles):
    """감성 분포 개요 계산."""
    if not articles:
        return {'positive': 0, 'neutral': 0, 'negative': 0, 'total': 0,
                'sentiment_index': 0, 'label': '중립/혼재', 'top_positive': [], 'top_negative': []}

    total = len(articles)
    pos = sum(1 for a in articles if a.get('sentiment') == 'positive')
    neu = sum(1 for a in articles if a.get('sentiment') == 'neutral')
    neg = sum(1 for a in articles if a.get('sentiment') == 'negative')

    sentiment_index = (pos - neg) / total if total else 0
    if sentiment_index >= 0.25:
        label = '긍정 우세'
    elif sentiment_index <= -0.25:
        label = '부정 우세'
    else:
        label = '중립/혼재'

    pos_articles = sorted([a for a in articles if a.get('sentiment') == 'positive'],
                          key=lambda x: x.get('final_score_100', 0) or 0, reverse=True)[:3]
    neg_articles = sorted([a for a in articles if a.get('sentiment') == 'negative'],
                          key=lambda x: x.get('final_score_100', 0) or 0, reverse=True)[:3]

    return {
        'positive': pos,
        'neutral': neu,
        'negative': neg,
        'total': total,
        'sentiment_index': round(sentiment_index, 4),
        'label': label,
        'top_positive': pos_articles,
        'top_negative': neg_articles,
    }


def calculate_source_reactions(articles):
    """매체별 반응 분석."""
    if not articles:
        return []

    groups = {}
    for a in articles:
        sid = a.get('source_id', 'unknown') or 'unknown'
        groups.setdefault(sid, []).append(a)

    max_count = max(len(v) for v in groups.values())

    results = []
    for sid, arts in groups.items():
        count = len(arts)
        scores = [a.get('final_score_100', 0) or 0 for a in arts]
        avg_final = sum(scores) / count
        sentiments = [a.get('sentiment', 'neutral') for a in arts]
        pos = sentiments.count('positive')
        neu = sentiments.count('neutral')
        neg = sentiments.count('negative')
        neg_ratio = neg / count
        hotness_vals = [a.get('hotness', 0) or 0 for a in arts]
        hotness_avg = sum(hotness_vals) / count

        count_norm = count / max_count if max_count else 0
        reaction_score = (
            avg_final * 0.45 +
            count_norm * 100 * 0.25 +
            neg_ratio * 100 * 0.20 +
            hotness_avg * 100 * 0.10
        )

        if neg_ratio >= 0.5 and avg_final >= 65:
            label = 'HOT RISK'
        elif reaction_score >= 75:
            label = 'HOT'
        elif reaction_score >= 45:
            label = 'WARM'
        else:
            label = 'COLD'

        top_art = max(arts, key=lambda x: x.get('final_score_100', 0) or 0)

        results.append({
            'source_id': sid,
            'source_name': arts[0].get('source_name', sid),
            'article_count': count,
            'avg_final_score': round(avg_final, 2),
            'positive_count': pos,
            'neutral_count': neu,
            'negative_count': neg,
            'negative_ratio': round(neg_ratio, 4),
            'hotness_avg': round(hotness_avg, 4),
            'source_reaction_score': round(reaction_score, 2),
            'label': label,
            'top_article_title': top_art.get('title', ''),
        })

    results.sort(key=lambda x: x['source_reaction_score'], reverse=True)
    return results
