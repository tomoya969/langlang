"""画面の HTML を静的に確かめる。ブラウザを動かさずに見つけられる食い違い（ファイルの名前、読み込む順）を拾う。"""

from __future__ import annotations

import re

import pytest

from tests.conftest import REPO_ROOT

STATIC = REPO_ROOT / "static"
PAGES = sorted(STATIC.glob("*.html"))
ASSET = re.compile(r'(?:src|href)="/static/([^"]+)"')
SCRIPT = re.compile(r'<script src="/static/([^"]+)"')


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_referenced_assets_exist(page):
    for asset in ASSET.findall(page.read_text(encoding="utf-8")):
        assert (STATIC / asset).is_file(), f"{page.name} が読み込む {asset} がありません"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_page_declares_scope(page):
    assert re.search(r'<body[^>]*data-scope="(portal|settings|language)"', page.read_text(encoding="utf-8")), page.name


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_script_order(page):
    """common.js（api・el・registerLanguagePack）は、それを使うスクリプトより先に読む。"""
    scripts = SCRIPT.findall(page.read_text(encoding="utf-8"))
    if "common.js" not in scripts:
        return
    common = scripts.index("common.js")
    for i, name in enumerate(scripts):
        if name.endswith("pack.js") or name in ("home.js", "learn.js", "words.js", "portal.js", "settings-page.js"):
            assert i > common, f"{page.name}: {name} は common.js より後に読む"
    for i, name in enumerate(scripts):
        if name.endswith("/pack.js"):
            lang_dir = name.rsplit("/", 1)[0]
            for dep in (f"{lang_dir}/keymap.js", f"{lang_dir}/composer.js"):
                assert dep in scripts[:i], f"{page.name}: {name} の前に {dep} を読む"


def test_language_pages_link_through_data_lang_path():
    """言語ごとの画面のナビは data-lang-path を持つ（JS が今の言語の URL に書き換えるため）。"""
    for name in ("index.html", "learn.html", "words.html"):
        html = (STATIC / name).read_text(encoding="utf-8")
        for href in re.findall(r'<a[^>]*href="(/ko[^"]*)"[^>]*>', html):
            tag = re.search(rf'<a[^>]*href="{re.escape(href)}"[^>]*>', html).group(0)
            assert "data-lang-path" in tag, f"{name}: {href} に data-lang-path がありません"
