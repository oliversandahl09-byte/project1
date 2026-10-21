(() => {
  const MAX_IMAGES = 5;
  const PLATFORM_NAMES = { vinted: "Vinted", depop: "Depop", grailed: "Grailed" };
  const LOADING_STEPS = [
    "Tolkar din stil…",
    "Söker på Vinted, Depop och Grailed…",
    "Kollar pris, storlek och skick…",
    "Väljer ut de bästa fynden…",
  ];

  const $ = (sel) => document.querySelector(sel);
  const chat = $("#chat");
  const form = $("#composer");
  const text = $("#text");
  const fileInput = $("#file");
  const thumbs = $("#thumbs");
  const sendBtn = $("#send");
  const dropHint = $("#drop-hint");

  let images = []; // { file, url }
  let history = []; // { role: "user" | "agent", text }
  let busy = false;

  function el(tag, cls, content) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (content != null) node.textContent = content;
    return node;
  }

  function safeUrl(url) {
    try {
      const u = new URL(url);
      return u.protocol === "https:" ? u.href : null;
    } catch {
      return null;
    }
  }

  function scrollDown() {
    chat.scrollTo({ top: chat.scrollHeight, behavior: "smooth" });
  }

  // --- Images: picker, drag and drop, paste ---------------------------------
  function addFiles(files) {
    for (const file of files) {
      if (!file.type.startsWith("image/")) continue;
      if (images.length >= MAX_IMAGES) break;
      images.push({ file, url: URL.createObjectURL(file) });
    }
    renderThumbs();
  }

  function renderThumbs() {
    thumbs.replaceChildren(
      ...images.map((img, i) => {
        const wrap = el("div", "thumb");
        const pic = el("img");
        pic.src = img.url;
        pic.alt = "Bifogad bild";
        const rm = el("button", null, "×");
        rm.type = "button";
        rm.setAttribute("aria-label", "Ta bort bild");
        rm.onclick = () => {
          URL.revokeObjectURL(img.url);
          images.splice(i, 1);
          renderThumbs();
        };
        wrap.append(pic, rm);
        return wrap;
      })
    );
  }

  fileInput.addEventListener("change", () => {
    addFiles(fileInput.files);
    fileInput.value = "";
  });
  document.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) addFiles(files);
  });
  ["dragenter", "dragover"].forEach((ev) =>
    document.addEventListener(ev, (e) => {
      if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
      e.preventDefault();
      form.classList.add("dragging");
      dropHint.hidden = false;
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    document.addEventListener(ev, (e) => {
      if (ev === "dragleave" && e.relatedTarget) return;
      form.classList.remove("dragging");
      dropHint.hidden = true;
    })
  );
  document.addEventListener("drop", (e) => {
    if (!e.dataTransfer?.files?.length) return;
    e.preventDefault();
    addFiles(e.dataTransfer.files);
  });

  // --- Text box --------------------------------------------------------------
  function autosize() {
    text.style.height = "auto";
    text.style.height = Math.min(text.scrollHeight, 180) + "px";
  }
  text.addEventListener("input", autosize);
  text.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  document.querySelectorAll(".example").forEach((b) =>
    b.addEventListener("click", () => {
      text.value = b.textContent;
      autosize();
      text.focus();
    })
  );
  $("#new-chat").addEventListener("click", () => location.reload());

  // --- Messages --------------------------------------------------------------
  function filterTags() {
    const tags = [];
    const price = $("#max_price").value;
    if (price) tags.push(`max ${price} kr`);
    if ($("#size").value.trim()) tags.push(`storlek ${$("#size").value.trim()}`);
    const gender = $("#gender").value;
    if (gender) tags.push(gender);
    const sites = [...document.querySelectorAll("input[name=platforms]:checked")].map((c) => PLATFORM_NAMES[c.value]);
    if (sites.length && sites.length < 3) tags.push(sites.join(" + "));
    return tags;
  }

  function addUserMessage(msgText, imgs) {
    const msg = el("div", "msg user");
    if (imgs.length) {
      const row = el("div", "imgs");
      imgs.forEach((img) => {
        const pic = el("img");
        pic.src = img.url;
        pic.alt = "Din bild";
        row.append(pic);
      });
      msg.append(row);
    }
    if (msgText) msg.append(el("div", "bubble", msgText));
    const tags = filterTags();
    if (tags.length) msg.append(el("div", "tags", tags.join(" · ")));
    chat.append(msg);
  }

  function addLoading() {
    const msg = el("div", "msg agent");
    const panel = el("div", "panel loading");
    const dots = el("span", "dots");
    dots.append(el("span"), el("span"), el("span"));
    const label = el("span", null, LOADING_STEPS[0]);
    panel.append(dots, label);
    msg.append(panel);
    chat.append(msg);
    let i = 0;
    const timer = setInterval(() => {
      i = Math.min(i + 1, LOADING_STEPS.length - 1);
      label.textContent = LOADING_STEPS[i];
    }, 9000);
    return { msg, stop: () => clearInterval(timer) };
  }

  function listingCard(item) {
    const tpl = $("#tpl-listing").content.cloneNode(true);
    const card = tpl.querySelector(".card");
    card.href = safeUrl(item.url) || "#";
    const badge = tpl.querySelector(".platform");
    badge.textContent = PLATFORM_NAMES[item.platform] || item.platform;
    badge.classList.add(item.platform);

    const photo = tpl.querySelector(".photo");
    const img = safeUrl(item.image_url || "");
    if (img) {
      const pic = el("img");
      pic.src = img;
      pic.alt = item.title;
      pic.loading = "lazy";
      pic.referrerPolicy = "no-referrer";
      pic.style.cssText = "width:100%;height:100%;object-fit:cover";
      pic.onerror = () => pic.replaceWith(el("span", null, "Ingen bild"));
      photo.prepend(pic);
    } else {
      photo.prepend(el("span", null, "Öppna för bilder"));
    }

    tpl.querySelector(".title").textContent = item.title;
    tpl.querySelector(".price").textContent = item.price || "";
    tpl.querySelector(".meta").textContent = [item.brand, item.size && `Stl ${item.size}`, item.condition]
      .filter(Boolean)
      .join(" · ");
    tpl.querySelector(".why").textContent = item.why || "";
    return tpl;
  }

  function renderResult(panel, data) {
    panel.className = "panel";
    panel.replaceChildren();
    if (data.style_summary) panel.append(el("p", "summary", data.style_summary));
    if (data.message) panel.append(el("p", "note", data.message));

    if (data.listings.length) {
      const grid = el("div", "grid");
      data.listings.forEach((item) => grid.append(listingCard(item)));
      panel.append(grid);
    }

    if (data.search_links.length) {
      const links = el("div", "links");
      links.append(el("h3", null, data.listings.length ? "Fortsätt leta själv" : "Sök direkt på sajterna"));
      const byQuery = new Map();
      data.search_links.forEach((l) => {
        if (!byQuery.has(l.query)) byQuery.set(l.query, []);
        byQuery.get(l.query).push(l);
      });
      byQuery.forEach((list, query) => {
        const row = el("div", "query");
        row.append(el("span", null, `”${query}”`));
        list.forEach((l) => {
          const a = el("a", `chip ${l.platform}`, PLATFORM_NAMES[l.platform]);
          a.href = safeUrl(l.url) || "#";
          a.target = "_blank";
          a.rel = "noopener";
          row.append(a);
        });
        links.append(row);
      });
      panel.append(links);
    }
  }

  // --- Submit ----------------------------------------------------------------
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;
    const msgText = text.value.trim();
    if (!msgText && !images.length) {
      text.focus();
      return;
    }

    $("#welcome")?.remove();
    const sent = images;
    addUserMessage(msgText, sent);

    const body = new FormData();
    body.append("text", msgText);
    sent.forEach((img) => body.append("images", img.file, img.file.name));
    document.querySelectorAll("input[name=platforms]:checked").forEach((c) => body.append("platforms", c.value));
    body.append("max_price", $("#max_price").value);
    body.append("size", $("#size").value);
    body.append("gender", $("#gender").value);
    body.append("history", JSON.stringify(history));

    images = [];
    renderThumbs();
    text.value = "";
    autosize();
    busy = true;
    sendBtn.disabled = true;
    const loading = addLoading();
    scrollDown();

    try {
      const res = await fetch("/api/search", { method: "POST", body });
      const data = await res.json().catch(() => ({ error: `Servern svarade ${res.status}` }));
      const panel = loading.msg.querySelector(".panel");
      if (!res.ok || data.error) {
        panel.className = "panel";
        panel.replaceChildren(el("p", "error", data.error || "Något gick fel."));
      } else {
        renderResult(panel, data);
        const userTurn = [msgText, sent.length ? `(${sent.length} bild${sent.length > 1 ? "er" : ""})` : ""]
          .filter(Boolean)
          .join(" ");
        const agentTurn = [
          data.style_summary,
          data.queries.length ? `Sökte: ${data.queries.join(", ")}` : "",
          data.listings.length
            ? `Visade: ${data.listings.slice(0, 8).map((l) => `${l.title} (${l.price || "?"})`).join("; ")}`
            : "",
        ]
          .filter(Boolean)
          .join("\n");
        history.push({ role: "user", text: userTurn }, { role: "agent", text: agentTurn });
      }
    } catch (err) {
      const panel = loading.msg.querySelector(".panel");
      panel.className = "panel";
      panel.replaceChildren(el("p", "error", "Kunde inte nå servern. Körs den fortfarande?"));
    } finally {
      loading.stop();
      busy = false;
      sendBtn.disabled = false;
      text.focus();
      scrollDown();
    }
  });
})();
