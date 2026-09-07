#!/usr/bin/env node
// Render LaTeX to static HTML with the vendored KaTeX, at build time (no client-side JS).
// stdin:  [{"tex": "...", "display": true|false}, ...]
// stdout: [{"html": "..."} | {"error": "..."}, ...]
const katex = require("./vendor/katex/katex.min.js");

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  const out = JSON.parse(input).map(({ tex, display }) => {
    try {
      return { html: katex.renderToString(tex, { displayMode: display, output: "htmlAndMathml", throwOnError: true, strict: "ignore" }) };
    } catch (e) {
      return { error: String(e.message || e) };
    }
  });
  process.stdout.write(JSON.stringify(out));
});
