/* Kleine Markdown-weergave voor de changelog. Ondersteunt alleen wat CHANGELOG.md gebruikt:
   koppen (#, ##, ###), lijsten (-), alinea's, **vet**, *cursief*, `code` en [tekst](url).
   Alle tekst wordt eerst ge-escaped; alleen http(s)-links worden links. Geen afhankelijkheden,
   zodat node dit bestand ook los kan testen (module.exports onderaan). */
"use strict";

function mdEscape(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function mdInline(text, refs) {
  const codes = [];
  let s = mdEscape(text).replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) => mdLink(label, url) ?? m);
  s = s.replace(/\[([^\]]+)\](?!\()/g, (m, label) => (refs[label.toLowerCase()] ? mdLink(label, refs[label.toLowerCase()]) : m));
  s = s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?!\w)/g, "$1<i>$2</i>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
}

function mdLink(label, url) {
  const u = url.replace(/&amp;/g, "&");
  if (!/^https?:\/\//i.test(u)) return null;
  return `<a href="${mdEscape(u)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
}

function renderMarkdown(src) {
  const refs = {};
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n").filter((ln) => {
    const m = ln.match(/^\s*\[([^\]]+)\]:\s*(\S+)\s*$/);
    if (m) { refs[m[1].toLowerCase()] = m[2]; return false; }
    return true;
  });
  const out = [];
  let para = [], list = null;
  const flushPara = () => { if (para.length) { out.push(`<p>${mdInline(para.join(" "), refs)}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`<ul>${list.map((li) => `<li>${mdInline(li, refs)}</li>`).join("")}</ul>`); list = null; } };
  for (const line of lines) {
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (h) {
      flushPara(); flushList();
      const level = Math.min(4, h[1].length + 1);  // # wordt h2: de dialoog heeft zelf al een titel
      out.push(`<h${level}>${mdInline(h[2], refs)}</h${level}>`);
    } else if (li) {
      flushPara();
      (list = list || []).push(li[1]);
    } else if (!line.trim()) {
      flushPara(); flushList();
    } else if (list && /^\s+\S/.test(line)) {
      list[list.length - 1] += " " + line.trim();  // vervolg van een lijstitem
    } else {
      flushList();
      para.push(line.trim().replace(/^>\s?/, ""));
    }
  }
  flushPara(); flushList();
  return out.join("\n");
}

if (typeof module !== "undefined") module.exports = { renderMarkdown };
