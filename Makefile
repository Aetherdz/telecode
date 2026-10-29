.PHONY: test check site

test:
	python3 -m unittest discover -s tests -v

check:
	python3 -m py_compile tg_bridge.py tg_mcp.py setup_cli.py get_telegram_id.py
	bash -n install.sh install_autostart.sh
	node --check assets/site.js
	python3 -c 'from html.parser import HTMLParser; HTMLParser().feed(open("index.html", encoding="utf-8").read())'

site:
	node --check assets/site.js
