# -*- coding: utf-8 -*-
"""fill.py — 三档填框（对齐 03-操作模式库 M3）

fill_input(tab, el_js, value):
    el_js  一个求值为目标元素的 JS 表达式（如 "document.querySelector('#kw')"）
    每档填完读回验证，不过就换下一档；整体重试 tries 轮；返回最终读回值（失败=''）。

适用：<input> / <textarea>。contenteditable 富文本框请直接用 tab.insert_text
（或走剪贴板粘贴，见 03-M7）。
"""
import json
import platform
import time

_SEL_MOD = 4 if platform.system() == "Darwin" else 2   # 全选快捷键修饰：mac=Cmd，其余=Ctrl


def read_value(tab, el_js):
    return tab.js("""(()=>{const el=%s;if(!el)return '';
if(el.value!==undefined)return String(el.value);
return String(el.innerText||el.textContent||'').trim()})()""" % el_js) or ""


def fill_input(tab, el_js, value, tries=3, verbose=True):
    for attempt in range(1, tries + 1):
        # ---- A 档：聚焦 + insertText（可信事件，首选）----
        st = tab.js("""(()=>{const el=%s;if(!el)return 'nf';el.focus();
if(el.select)try{el.select()}catch(e){}return 'ok'})()""" % el_js)
        if st == "ok":
            time.sleep(0.15)
            tab.insert_text(value)
            time.sleep(0.35)
            v = read_value(tab, el_js)
            if v:
                if verbose:
                    print("  fill ok(A):", v[:40])
                return v

        # ---- B 档：原生 setter + input/change（React 受控组件兜底）----
        tab.js("""(()=>{const el=%s;if(!el)return 'nf';
const proto = el.tagName==='TEXTAREA' ? window.HTMLTextAreaElement.prototype
                                      : window.HTMLInputElement.prototype;
const s = Object.getOwnPropertyDescriptor(proto,'value').set;
try{ s.call(el, %s) }catch(e){ el.value = %s }
el.dispatchEvent(new Event('input', {bubbles:true}));
el.dispatchEvent(new Event('change', {bubbles:true}));
return 'ok'})()""" % (el_js, json.dumps(value, ensure_ascii=False),
                      json.dumps(value, ensure_ascii=False)))
        time.sleep(0.3)
        v = read_value(tab, el_js)
        if v:
            if verbose:
                print("  fill ok(B):", v[:40])
            return v

        # ---- C 档：真鼠标聚焦 → Ctrl+A → insertText ----
        rc = tab.js("""(()=>{const el=%s;if(!el)return null;
const r = el.getBoundingClientRect();
return JSON.stringify({x:r.x+r.width/2, y:r.y+r.height/2})})()""" % el_js)
        if rc and str(rc).startswith("{"):
            rc = json.loads(rc)
            x, y = tab.clamp(rc["x"], rc["y"])
            tab.click_xy(x, y)
            time.sleep(0.25)
            tab.call("Input.dispatchKeyEvent", type="rawKeyDown",
                     windowsVirtualKeyCode=65, key="a", code="KeyA", modifiers=_SEL_MOD)
            tab.call("Input.dispatchKeyEvent", type="keyUp",
                     windowsVirtualKeyCode=65, key="a", code="KeyA", modifiers=_SEL_MOD)
            time.sleep(0.1)
            tab.insert_text(value)
            time.sleep(0.35)
            v = read_value(tab, el_js)
            if v:
                if verbose:
                    print("  fill ok(C):", v[:40])
                return v

        if verbose:
            print("  fill attempt %d failed" % attempt)
        time.sleep(0.3)
    return ""
