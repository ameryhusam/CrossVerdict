# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import re

class CrossVerdict(gl.Contract):
    # ---- History (key = URL) ----
    product_names: TreeMap[str, str]
    prices: TreeMap[str, str]
    ratings_scaled: TreeMap[str, u256]          # rating * 10
    review_snippets: TreeMap[str, str]          # cleaned first sentence
    analyzed_urls: DynArray[str]

    # ---- Latest session ----
    last_session_urls: DynArray[str]            # URLs in last analyze()
    last_best_url: str
    last_ranking_text: str

    def __init__(self):
        self.last_best_url = ""
        self.last_ranking_text = ""

    # ============================
    #  MAIN ENTRY – up to 3 URLs
    # ============================
    @gl.public.write
    def analyze(self, url1: str = "", url2: str = "", url3: str = "") -> str:
        urls = [u for u in [url1, url2, url3] if u.strip()]
        if not urls:
            return "Please provide at least one product URL."

        self.last_session_urls = []
        for url in urls:
            if url not in self.product_names:
                self._extract_and_store(url)
            self.last_session_urls.append(url)

        ranking, best_url = self._compute_ranking(self.last_session_urls)
        self.last_best_url = best_url
        self.last_ranking_text = ranking

        return (
            f"Best choice: {self.product_names[best_url]} "
            f"(Rating: {self.ratings_scaled[best_url] / 10}/5, Price: {self.prices[best_url]})\n\n"
            f"Full ranking:\n{ranking}"
        )

    # ============================
    #  DETERMINISTIC EXTRACTION
    # ============================
    def _extract_and_store(self, url: str):
        def extract() -> dict:
            html = gl.nondet.web.get(url).body.decode("utf-8", errors="ignore")

            # 1. Product name – best effort to remove store labels
            t = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            title = t.group(1).strip() if t else "Unknown"
            # Remove trailing " : Amazon.com" or " - Store" etc.
            name = re.sub(r'\s*[-–|:]\s*(Amazon\.com|BestBuy|Walmart|eBay|AliExpress|Target|Shopify).*$', '', title, flags=re.IGNORECASE).strip()
            # If still contains a colon after other text, keep the longer part as product name
            if ':' in name:
                parts = name.split(':', 1)
                name = parts[1].strip() if len(parts[1]) > len(parts[0]) else parts[0].strip()
            if not name:
                name = title

            # 2. Price – first $xx.xx or £xx.xx
            p = re.search(r"[\$\£]\s?\d+\.?\d{0,2}", html)
            price = p.group(0) if p else "N/A"

            # 3. Star rating (common patterns)
            star = 0.0
            m = re.search(r'(\d\.?\d?)\s*out of\s*5', html, re.IGNORECASE)
            if not m:
                m = re.search(r'"ratingValue":\s*"?([\d.]+)"?', html)
            if not m:
                m = re.search(r'a-star-(\d)', html)
            if m:
                try:
                    star = float(m.group(1))
                except:
                    pass

            # 4. Review snippets – skip lines that are just a rating number
            patterns = [
                r'<span[^>]*data-hook="review-body"[^>]*>(.*?)</span>',
                r'<p[^>]*class="[^"]*review[^"]*"[^>]*>(.*?)</p>',
                r'<div[^>]*class="[^"]*review[^"]*"[^>]*>(.*?)</div>',
            ]
            snippets = []
            for pat in patterns:
                matches = re.findall(pat, html, re.DOTALL | re.IGNORECASE)
                for m_text in matches:
                    clean = re.sub(r'<.*?>', '', m_text).strip()
                    # Ignore lines that are only numbers/punctuation (likely stray rating)
                    if clean and not re.match(r'^[\d\.\s\-\—\&\,\#\;\:\!\?\(\)\[\]\{\}\@\$\^\%\*\+\=\|\/\\\'\"\`\~\_]*$', clean):
                        snippets.append(clean)
                    if len(snippets) >= 3:
                        break
                if snippets:
                    break
            # Take first sentence of the first review
            first_review = snippets[0] if snippets else ""
            first_sentence = first_review.split('.')[0].strip() + '.' if first_review else "No reviews"

            return {
                "name": name,
                "price": price,
                "rating_scaled": int(star * 10),
                "review_sentence": first_sentence
            }

        info = gl.eq_principle.strict_eq(extract)

        self.product_names[url] = info["name"]
        self.prices[url] = info["price"]
        self.ratings_scaled[url] = u256(info["rating_scaled"])
        self.review_snippets[url] = info["review_sentence"]

        if url not in self.analyzed_urls:
            self.analyzed_urls.append(url)

    # ============================
    #  RANKING (deterministic)
    # ============================
    def _compute_ranking(self, urls: DynArray[str]):
        products = []
        for url in urls:
            name = self.product_names.get(url, "Unknown")
            price_str = self.prices.get(url, "N/A")
            rating = int(self.ratings_scaled.get(url, u256(0)))
            review = self.review_snippets.get(url, "")

            price_val = 9999.0
            m = re.search(r"[\d\.]+", price_str.replace(",", ""))
            if m:
                try:
                    price_val = float(m.group())
                except:
                    pass
            products.append({
                "name": name,
                "price": price_str,
                "rating": rating,
                "review": review,
                "url": url,
                "price_val": price_val
            })

        products.sort(key=lambda x: (-x["rating"], x["price_val"]))

        lines = []
        for i, p in enumerate(products, 1):
            rating_display = p["rating"] / 10.0
            lines.append(
                f"{i}. {p['name']} – Rating: {rating_display}/5, Price: {p['price']}, "
                f"Review: {p['review']}"
            )
        ranking = "\n".join(lines)
        best_url = products[0]["url"] if products else ""
        return ranking, best_url

    # ============================
    #  VIEW METHODS (all safe types)
    # ============================
    @gl.public.view
    def get_best_name(self) -> str:
        if not self.last_best_url:
            return "No analysis yet"
        return self.product_names[self.last_best_url]

    @gl.public.view
    def get_best_price(self) -> str:
        if not self.last_best_url:
            return "N/A"
        return self.prices[self.last_best_url]

    @gl.public.view
    def get_best_rating(self) -> u256:
        """Returns rating * 10 (e.g., 44 means 4.4)"""
        if not self.last_best_url:
            return u256(0)
        return self.ratings_scaled[self.last_best_url]

    @gl.public.view
    def get_best_review(self) -> str:
        if not self.last_best_url:
            return ""
        return self.review_snippets[self.last_best_url]

    @gl.public.view
    def get_best_compared_urls(self) -> str:
        """Returns the URLs that were compared to pick this best product."""
        if not self.last_session_urls:
            return "No session data"
        # Return as newline-separated string
        return "\n".join([u for u in self.last_session_urls])

    @gl.public.view
    def get_ranking(self) -> str:
        return self.last_ranking_text

    @gl.public.view
    def get_history(self) -> str:
        """All stored products, one per line."""
        if not self.analyzed_urls:
            return "No products analyzed yet."
        lines = []
        for url in self.analyzed_urls:
            name = self.product_names.get(url, "")
            price = self.prices.get(url, "")
            rating = self.ratings_scaled.get(url, u256(0)) / 10.0
            lines.append(f"{name} | {price} | Rating: {rating}/5")
        return "\n".join(lines)