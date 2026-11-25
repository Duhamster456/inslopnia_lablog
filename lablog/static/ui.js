async function copyText(text) {
    if (navigator.clipboard) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch {
            // Clipboard permissions vary between browsers and origins.
        }
    }

    const focused = document.activeElement;
    const buffer = document.createElement("textarea");
    buffer.className = "clipboard-buffer";
    buffer.readOnly = true;
    buffer.tabIndex = -1;
    buffer.value = text;
    document.body.append(buffer);
    buffer.focus({ preventScroll: true });
    buffer.select();
    try {
        return document.execCommand("copy");
    } catch {
        return false;
    } finally {
        buffer.remove();
        focused?.focus({ preventScroll: true });
    }
}

const copyStatus = document.getElementById("copy-status");
for (const button of document.querySelectorAll("[data-copy]")) {
    const target = document.getElementById(button.dataset.copy);
    if (!target) continue;
    button.hidden = false;
    let reset;
    button.addEventListener("click", async () => {
        const isInput = target instanceof HTMLInputElement;
        const copied = await copyText(isInput ? target.value : target.textContent);
        if (!copied) {
            if (isInput) {
                target.focus();
                target.select();
            } else {
                const selection = window.getSelection();
                const range = document.createRange();
                range.selectNodeContents(target);
                selection.removeAllRanges();
                selection.addRange(range);
            }
        }
        button.textContent = copied ? "Скопировано" : "Выделено";
        copyStatus.textContent = copied ? "Скопировано в буфер обмена." : "Текст выделен для копирования.";
        clearTimeout(reset);
        reset = setTimeout(() => {
            button.textContent = "Копировать";
            copyStatus.textContent = "";
        }, 2200);
    });
}
