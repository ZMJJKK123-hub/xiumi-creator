"""注入页面的 JS 操作库（模拟真实用户操作）。

以 `window.__agent` 挂载；outline() 给可交互元素分配 ref，
其余 API 用 ref 定位元素。ref 在下一次 outline()/find() 前有效。
"""
from __future__ import annotations


def call_expr(fn: str, *args) -> str:
    """生成 window.__agent.fn(arg1, arg2, ...) 的调用表达式。"""
    import json

    return f"window.__agent.{fn}(...{json.dumps(list(args), ensure_ascii=False)})"


# evaluate 时整体执行一次即可（幂等：已存在则直接复用）
AGENT_JS = r"""
(function () {
  if (window.__agent && window.__agent.__ok) return 'already';
  var counter = 0;
  var nodes = new Map();

  var INTERACTIVE = new Set(['a', 'button', 'input', 'textarea', 'select', 'summary', 'option']);
  function isInteractive(el) {
    var tag = el.tagName.toLowerCase();
    if (INTERACTIVE.has(tag)) return true;
    var role = el.getAttribute && (el.getAttribute('role') || '');
    if (/button|link|tab|textbox|menuitem|option/i.test(role)) return true;
    if (el.isContentEditable) return true;
    if (el.hasAttribute && (el.hasAttribute('onclick') || el.hasAttribute('ng-click'))) return true;
    return false;
  }
  function visible(el) {
    var r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    var s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none';
  }
  function directText(el) {
    var t = '';
    for (var i = 0; i < el.childNodes.length; i++) {
      var n = el.childNodes[i];
      if (n.nodeType === 3) t += n.textContent;
    }
    return t.replace(/\s+/g, ' ').trim();
  }
  function clip(s, n) {
    s = (s || '').replace(/\s+/g, ' ').trim();
    return s.length > n ? s.slice(0, n) + '…' : s;
  }
  function describe(el) {
    var d = { tag: el.tagName.toLowerCase() };
    if (el.id) d.id = el.id;
    var cls = (typeof el.className === 'string' ? el.className : '').trim();
    if (cls) d.cls = clip(cls.split(/\s+/).slice(0, 3).join('.'), 40);
    var label = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder');
    if (label) d.label = clip(label, 40);
    if (el.value !== undefined && el.value !== null && el.value !== '') d.value = clip(String(el.value), 40);
    if (el.isContentEditable) d.editable = true;
    if (el.tagName === 'IFRAME') d.src = clip(el.src || el.getAttribute('src') || '', 100);
    var own = directText(el);
    if (own) d.text = clip(own, 60);
    return d;
  }
  // 只展开「可交互 / 含直接文本 / iframe」的节点，控制体积
  function walk(el, out, depth) {
    if (nodes.size > 400) return;
    var kids = el.children;
    for (var i = 0; i < kids.length; i++) {
      var child = kids[i];
      if (!visible(child)) continue;
      var keep = isInteractive(child) || directText(child) || child.tagName === 'IFRAME';
      if (keep) {
        counter += 1;
        nodes.set(counter, child);
        var d = describe(child);
        d.ref = counter;
        out.push(d);
        if (depth < 14 && child.children.length && child.tagName !== 'IFRAME') {
          d.children = [];
          walk(child, d.children, depth + 1);
        }
      } else if (child.children.length) {
        walk(child, out, depth);
      }
    }
  }
  function outline() {
    counter = 0; nodes.clear();
    var root = { tag: 'body', children: [] };
    walk(document.body, root.children, 0);
    return { url: location.href, title: document.title, refs: nodes.size, tree: root };
  }

  function need(ref) {
    var el = nodes.get(ref);
    if (!el || !el.isConnected) throw new Error('ref ' + ref + ' 已失效，请重新执行 dom_outline');
    return el;
  }

  function click(ref) {
    var el = need(ref);
    el.scrollIntoView({ block: 'center', inline: 'center' });
    var r = el.getBoundingClientRect();
    var x = r.left + r.width / 2, y = r.top + r.height / 2;
    var base = { bubbles: true, cancelable: true, composed: true, view: window, clientX: x, clientY: y, button: 0 };
    try {
      el.dispatchEvent(new PointerEvent('pointerover', Object.assign({ isPrimary: true, pointerType: 'mouse' }, base)));
      el.dispatchEvent(new MouseEvent('mouseover', base));
      el.dispatchEvent(new PointerEvent('pointerdown', Object.assign({ isPrimary: true, pointerType: 'mouse' }, base)));
      el.dispatchEvent(new MouseEvent('mousedown', base));
      el.dispatchEvent(new PointerEvent('pointerup', Object.assign({ isPrimary: true, pointerType: 'mouse' }, base)));
      el.dispatchEvent(new MouseEvent('mouseup', base));
      el.dispatchEvent(new MouseEvent('click', base));
    } catch (e) {
      el.click();
    }
    return true;
  }

  function type(ref, text) {
    var el = need(ref);
    el.scrollIntoView({ block: 'center' });
    el.focus();
    var tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea') {
      var proto = tag === 'input' ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
      var setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, text);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      // contenteditable：execCommand 会触发原生 input 事件，编辑器框架可感知
      el.focus();
      document.execCommand('selectAll', false, null);
      document.execCommand('insertText', false, text);
    }
    return true;
  }

  function press(key) {
    var t = document.activeElement;
    if (!t) return false;
    var o = { key: key, bubbles: true, cancelable: true };
    t.dispatchEvent(new KeyboardEvent('keydown', o));
    if (key === 'Enter') t.dispatchEvent(new KeyboardEvent('keypress', o));
    t.dispatchEvent(new KeyboardEvent('keyup', o));
    return true;
  }

  function find(selector, limit) {
    limit = limit || 20;
    var out = [];
    var els = document.querySelectorAll(selector);
    for (var i = 0; i < els.length && out.length < limit; i++) {
      var el = els[i];
      counter += 1;
      nodes.set(counter, el);
      var d = describe(el);
      d.ref = counter;
      out.push(d);
    }
    return out;
  }

  function findByText(text, selector, limit) {
    limit = limit || 8;
    selector = selector || 'button, a, span, li, div[role], p, h1, h2, h3, h4';
    var want = String(text).replace(/\s+/g, '');
    var out = [];
    var els = document.querySelectorAll(selector);
    for (var i = 0; i < els.length; i++) {
      if (out.length >= limit) break;
      var el = els[i];
      if (!visible(el)) continue;
      var own = directText(el).replace(/\s+/g, '');
      if (own && own.indexOf(want) !== -1) {
        counter += 1;
        nodes.set(counter, el);
        var d = describe(el);
        d.ref = counter;
        out.push(d);
      }
    }
    return out;
  }

  function getText(ref, max) {
    var el = need(ref);
    return clip(el.innerText || el.textContent || '', max || 3000);
  }

  // ===== 编辑区操作（元素级核心，selector 版是对外包装）=====

  function elOf(selectorOrEl) {
    if (typeof selectorOrEl === 'string') {
      var el = document.querySelector(selectorOrEl);
      if (!el) throw new Error('找不到元素: ' + selectorOrEl);
      return el;
    }
    return selectorOrEl;
  }

  function focusEndEl(el) {
    el.focus();
    var sel = window.getSelection();
    var range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  }

  function focusEnd(selector) {
    return focusEndEl(elOf(selector));
  }

  function pasteHTMLEl(target, html) {
    var dt = new DataTransfer();
    dt.setData('text/html', html);
    dt.setData('text/plain', html.replace(/<[^>]+>/g, ''));
    var ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
    target.dispatchEvent(ev);
    return { dispatched: true, acceptedByEditor: ev.defaultPrevented };
  }

  function pasteHTML(html, selector) {
    var target = selector ? elOf(selector) : document.activeElement;
    if (!target) throw new Error('pasteHTML: 没有目标');
    if (!target.isContentEditable && !/input|textarea/i.test(target.tagName)) {
      throw new Error('pasteHTML: 目标不是可编辑区域');
    }
    if (selector) focusEndEl(target);
    return pasteHTMLEl(target, html);
  }

  function appendHTMLEl(el, html) {
    var tpl = document.createElement('template');
    tpl.innerHTML = html;
    el.appendChild(tpl.content);
    el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste' }));
    return true;
  }

  function appendHTML(html, selector) {
    var el = elOf(selector || '[contenteditable="true"]');
    return appendHTMLEl(el, html);
  }

  // 选择面积最大的 contenteditable 作为正文编辑区，末尾插入 HTML
  function editorInsert(html) {
    var els = Array.prototype.slice.call(document.querySelectorAll('[contenteditable="true"]'));
    if (!els.length) throw new Error('未找到编辑区(contenteditable)');
    var ed = null, max = 0;
    els.forEach(function (e) {
      if (!visible(e)) return;
      var r = e.getBoundingClientRect();
      var area = r.width * r.height;
      if (area > max) { max = area; ed = e; }
    });
    if (!ed) throw new Error('编辑区不可见');
    ed.scrollIntoView({ block: 'end' });
    focusEndEl(ed);
    var res = pasteHTMLEl(ed, html);
    if (!res.acceptedByEditor) {
      appendHTMLEl(ed, html);
      return { mode: 'append(fallback)' };
    }
    return { mode: 'paste' };
  }

  // 当前最大编辑区的信息（确认编辑器已加载）
  function editorInfo() {
    var els = Array.prototype.slice.call(document.querySelectorAll('[contenteditable="true"]'));
    var best = null, max = 0;
    els.forEach(function (e) {
      var r = e.getBoundingClientRect();
      var area = r.width * r.height;
      if (area > max) { max = area; best = e; }
    });
    if (!best) return null;
    counter += 1; nodes.set(counter, best);
    return { ref: counter, cls: clip(best.className, 60), blocks: best.children.length };
  }

  function triggerChange(selector) {
    var el = elOf(selector);
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  }

  window.__agent = {
    __ok: true,
    outline: outline,
    click: click,
    type: type,
    press: press,
    find: find,
    findByText: findByText,
    getText: getText,
    focusEnd: focusEnd,
    pasteHTML: pasteHTML,
    appendHTML: appendHTML,
    editorInsert: editorInsert,
    editorInfo: editorInfo,
    triggerChange: triggerChange,
  };
  return 'ok';
})()
"""
