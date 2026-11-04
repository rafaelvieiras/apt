// Progressive enhancement: copy buttons and the package filter.
// Every page is complete without this file; it only reveals controls that need JavaScript.
const live = document.getElementById("live");
let liveTimer;

function announce(text) {
  if (!live) return;
  live.textContent = text;
  clearTimeout(liveTimer);
  liveTimer = setTimeout(() => (live.textContent = ""), 2500);
}

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  return new Promise((resolve, reject) => {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;opacity:0";
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy") ? resolve() : reject(new Error("copy refused"));
    } catch (error) {
      reject(error);
    } finally {
      area.remove();
    }
  });
}

for (const button of document.querySelectorAll("button[data-copy]")) {
  button.hidden = false;
  const label = button.textContent;
  let timer;
  button.addEventListener("click", () => {
    const flash = (text, message) => {
      button.textContent = text;
      announce(message);
      clearTimeout(timer);
      timer = setTimeout(() => (button.textContent = label), 1800);
    };
    copyText(button.dataset.copy).then(
      () => flash("Copied", "Copied to clipboard"),
      () => flash("Press Ctrl+C", "Copy failed. Select the text and press Ctrl+C"),
    );
  });
}

const box = document.getElementById("filter-box");
const input = document.getElementById("filter");
if (box && input) {
  box.hidden = false;
  const rows = [...document.querySelectorAll("[data-row]")];
  const groups = [...document.querySelectorAll("[data-group]")];
  const count = document.getElementById("filter-count");
  const empty = document.getElementById("filter-empty");
  const total = rows.length;

  const apply = () => {
    const words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const row of rows) {
      const hay = row.dataset.search;
      const match = words.every((word) => hay.includes(word));
      row.hidden = !match;
      if (match) shown++;
    }
    for (const group of groups) group.hidden = !group.querySelector("[data-row]:not([hidden])");
    empty.hidden = shown > 0;
    count.textContent = words.length ? `${shown} of ${total} listed` : `${total} listed`;
  };

  input.addEventListener("input", apply);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && input.value) {
      input.value = "";
      apply();
    }
  });
  apply();
}
