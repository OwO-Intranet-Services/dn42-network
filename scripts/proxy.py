from flask import Flask, request, Response, session
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

app = Flask(__name__)
app.secret_key = 'CHANGE_THIS_TO_RANDOM_SECRET'

PROXY_URL = "http://127.0.0.1:5000"

# --- THE JAVASCRIPT HOOK ---
# This JS runs in the browser to catch client-side requests
JS_HOOK = f"""
<script>
(function() {{
    const PROXY_URL = "{PROXY_URL}";
    
    // Helper: Rewrite URL to go through proxy
    function rewriteUrl(url) {{
        if (!url) return url;
        // If already proxied, skip
        if (url.toString().startsWith(PROXY_URL)) return url;
        // If data URI or blob, skip
        if (url.toString().startsWith('data:') || url.toString().startsWith('blob:')) return url;
        
        // Calculate absolute URL based on current "virtual" page
        // We look for ?url=... in the current address bar
        const params = new URLSearchParams(window.location.search);
        let baseUrl = params.get('url');
        if (!baseUrl) return url; // Fallback

        // Handle absolute vs relative
        try {{
            const absoluteUrl = new URL(url, baseUrl).href;
            return PROXY_URL + '/?url=' + encodeURIComponent(absoluteUrl);
        }} catch(e) {{
            return url;
        }}
    }}

    // Function to apply the hooks
    function applyHooks() {{
        // 1. Monkey Patch window.fetch
        const originalFetch = window.fetch;
        window.fetch = function(input, init) {{
            // Input can be a string or a Request object
            if (typeof input === 'string') {{
                input = rewriteUrl(input);
            }} else if (input instanceof Request) {{
                // Clone the request with new URL
                input = new Request(rewriteUrl(input.url), input);
            }}
            return originalFetch(input, init);
        }};

        // 2. Monkey Patch XMLHttpRequest (XHR)
        const originalOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url, ...args) {{
            const newUrl = rewriteUrl(url);
            return originalOpen.call(this, method, newUrl, ...args);
        }};

        // 3. Monkey Patch WebSocket (optional)
        const OriginalWebSocket = window.WebSocket;
        window.WebSocket = function(url, protocols) {{
            const newUrl = rewriteUrl(url);
            return new OriginalWebSocket(newUrl, protocols);
        }};
        window.WebSocket.prototype = OriginalWebSocket.prototype;

        console.log("Proxy Hook Applied");
    }}

    // Apply hooks initially
    applyHooks();

    // Run every 5 seconds
    setInterval(applyHooks, 5000);

    console.log("Proxy Hook Injected Successfully");
}})();
</script>
"""

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE'])
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def proxy(path):
    target_url = request.args.get('url')

    # --- URL Resolution ---
    if not target_url:
        referer = request.headers.get('Referer')
        if referer and 'url=' in referer:
            try:
                ref_parsed = urlparse(referer)
                ref_query = parse_qs(ref_parsed.query)
                parent_url = ref_query.get('url', [None])[0]
                if parent_url:
                    target_url = urljoin(parent_url, request.full_path.lstrip('/'))
            except:
                pass
        
        if not target_url:
            base_url = session.get('active_base_url')
            if not base_url:
                return "No URL specified. Go to /?url=http://example.com"
            target_url = urljoin(base_url, request.full_path.lstrip('/'))
    else:
        parsed = urlparse(target_url)
        session['active_base_url'] = f"{parsed.scheme}://{parsed.netloc}"

    try:
        # --- Headers & Request ---
        parsed_target = urlparse(target_url)
        base_domain = f"{parsed_target.scheme}://{parsed_target.netloc}"

        req_headers = {k: v for k, v in request.headers if k.lower() not in ['host', 'accept-encoding', 'origin', 'referer', 'content-length']}
        req_headers['Host'] = parsed_target.netloc
        req_headers['Referer'] = base_domain
        req_headers['Origin'] = base_domain

        resp = requests.request(
            request.method, 
            target_url, 
            headers=req_headers, 
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=True,
            verify=False
        )

        final_parsed = urlparse(resp.url)
        session['active_base_url'] = f"{final_parsed.scheme}://{final_parsed.netloc}"

        # --- Content Processing ---
        content = resp.content
        resp_headers = [(name, value) for (name, value) in resp.headers.items() 
                        if name.lower() not in ['content-encoding', 'content-length', 'transfer-encoding', 'connection', 'location']]

        if 'text/html' in resp.headers.get('Content-Type', '').lower():
            try:
                soup = BeautifulSoup(content, 'html.parser')
                
                # A. Rewrite Static Tags
                tags_to_modify = [
                    ('a', 'href'), ('img', 'src'), ('link', 'href'), 
                    ('script', 'src'), ('form', 'action'), ('iframe', 'src')
                ]
                
                for tag, attr in tags_to_modify:
                    for node in soup.find_all(tag):
                        if node.get('integrity'): del node['integrity']
                        
                        val = node.get(attr)
                        if val:
                            absolute_url = urljoin(resp.url, val)
                            node[attr] = f"{PROXY_URL}/?url={absolute_url}"


                for tag in soup.find_all(['script', 'style']):
                    original_text = tag.string if tag.string is not None else tag.decode_contents()
                    if not original_text:
                        continue

                    base_protocol = urlparse(resp.url).scheme
                    new_text = re.sub(r'\$\{location\.protocol\}//', f'{base_protocol}://', original_text)

                    def _proxify(m):
                        url = m.group(1)
                        if url.startswith(PROXY_URL):
                            return url
                        return f"{PROXY_URL}/?url={quote(url, safe='')}"
                    new_text = re.sub(r'(https?://[^\'"\s<>)]+)', _proxify, new_text)

                    if tag.string is not None:
                        tag.string.replace_with(new_text)
                    else:
                        tag.clear()
                        tag.append(BeautifulSoup(new_text, 'html.parser'))

                html_text = str(soup)
                html_text = re.sub(r'(https?://[^\'"\s<>)]+)', lambda m: m.group(1) if m.group(1).startswith(PROXY_URL) else f"{PROXY_URL}/?url={quote(m.group(1), safe='')}", html_text)
                soup = BeautifulSoup(html_text, 'html.parser')
                if soup.head:
                    soup.head.insert(0, BeautifulSoup(JS_HOOK, 'html.parser'))
                elif soup.body:
                    soup.body.insert(0, BeautifulSoup(JS_HOOK, 'html.parser'))

                content = str(soup).encode('utf-8')
                
                resp_headers = [(k, v) for k, v in resp_headers if k.lower() != 'content-type']
                resp_headers.append(('Content-Type', 'text/html; charset=utf-8'))

            except Exception as e:
                pass

        response = Response(content, resp.status_code, resp_headers)
        
        for cookie in resp.cookies:
            response.set_cookie(cookie.name, cookie.value, path=cookie.path, secure=False, httponly=False)

        return response

    except Exception as e:
        return f"Proxy Error: {e}", 500

if __name__ == '__main__':
    import urllib3
    import re
    from urllib.parse import quote
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    app.run(debug=True, port=5000)