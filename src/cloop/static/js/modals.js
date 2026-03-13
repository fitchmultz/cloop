/**
 * modals.js - Modal handling
 *
 * Purpose:
 *   Manage modal dialogs and overlays.
 *
 * Responsibilities:
 *   - Help modal show/hide
 *   - Reusable form/confirm/notice dialogs
 *   - Modal backdrop clicks and focus management
 *   - Modal state tracking
 *
 * Non-scope:
 *   - Merge modal content (see duplicates.js)
 *   - Keyboard shortcuts (see keyboard.js)
 */

let helpModal;
let appDialog;
let appDialogPanel;
let appDialogForm;
let appDialogEyebrow;
let appDialogTitle;
let appDialogDescription;
let appDialogFields;
let appDialogError;
let appDialogCancel;
let appDialogConfirm;
let isHelpModalOpen = false;
let activeDialogResolver = null;
let activeDialogConfig = null;
let lastFocusedElement = null;

const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

/**
 * Initialize modals module
 */
export function init(elements) {
  helpModal = elements.helpModal;
  appDialog = elements.appDialog;
  appDialogPanel = appDialog?.querySelector(".app-dialog");
  appDialogForm = document.getElementById("app-dialog-form");
  appDialogEyebrow = document.getElementById("app-dialog-eyebrow");
  appDialogTitle = document.getElementById("app-dialog-title");
  appDialogDescription = document.getElementById("app-dialog-description");
  appDialogFields = document.getElementById("app-dialog-fields");
  appDialogError = document.getElementById("app-dialog-error");
  appDialogCancel = document.getElementById("app-dialog-cancel");
  appDialogConfirm = document.getElementById("app-dialog-confirm");

  helpModal.addEventListener("click", (event) => {
    if (event.target === helpModal) {
      showHelpModal(false);
    }
  });

  const closeBtn = helpModal.querySelector("[data-action=close-help]");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => showHelpModal(false));
  }

  appDialog?.addEventListener("click", (event) => {
    if (event.target === appDialog && activeDialogConfig?.dismissible !== false) {
      closeDialog(null);
    }
  });

  appDialogForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!activeDialogConfig) {
      return;
    }

    const values = collectDialogValues();
    const validationMessage = activeDialogConfig.validate?.(values) ?? null;
    if (validationMessage) {
      showDialogError(validationMessage);
      focusFirstField();
      return;
    }

    closeDialog(values);
  });

  appDialog?.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && activeDialogConfig?.dismissible !== false) {
      event.preventDefault();
      closeDialog(null);
      return;
    }

    if (event.key === "Tab") {
      trapFocus(event);
    }
  });

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-action='cancel-app-dialog'], [data-action='close-app-dialog']")) {
      closeDialog(null);
    }
  });
}

/**
 * Show or hide help modal
 */
export function showHelpModal(show) {
  if (show) {
    helpModal.classList.add("visible");
    helpModal.querySelector(".help-modal").focus();
    isHelpModalOpen = true;
  } else {
    helpModal.classList.remove("visible");
    isHelpModalOpen = false;
  }
}

/**
 * Check if any modal is open
 */
export function isModalOpen() {
  return isHelpModalOpen || !appDialog?.hidden || document.getElementById("mergeModal")?.classList.contains("visible");
}

function renderDialogFields(fields) {
  if (!appDialogFields) {
    return;
  }

  appDialogFields.innerHTML = "";

  fields.forEach((field, index) => {
    const fieldId = `app-dialog-field-${field.name}`;
    const wrapper = document.createElement("label");
    wrapper.className = "app-dialog-field";
    wrapper.htmlFor = fieldId;

    const label = document.createElement("span");
    label.className = "app-dialog-label";
    label.textContent = field.label;
    wrapper.appendChild(label);

    let control;
    if (field.type === "textarea") {
      control = document.createElement("textarea");
      control.rows = field.rows ?? 4;
    } else if (field.type === "select") {
      control = document.createElement("select");
      (field.options ?? []).forEach((option) => {
        const optionEl = document.createElement("option");
        optionEl.value = option.value;
        optionEl.textContent = option.label;
        if (option.value === field.value) {
          optionEl.selected = true;
        }
        control.appendChild(optionEl);
      });
    } else {
      control = document.createElement("input");
      control.type = field.type ?? "text";
    }

    control.id = fieldId;
    control.name = field.name;
    control.className = "app-dialog-input";
    control.value = field.value ?? "";
    control.required = field.required ?? false;

    if (field.placeholder) {
      control.placeholder = field.placeholder;
    }
    if (field.autocomplete) {
      control.autocomplete = field.autocomplete;
    }
    if (field.inputMode) {
      control.inputMode = field.inputMode;
    }
    if (field.maxLength) {
      control.maxLength = field.maxLength;
    }

    if (index === 0) {
      control.dataset.initialFocus = "true";
    }

    wrapper.appendChild(control);

    if (field.helpText) {
      const help = document.createElement("span");
      help.className = "app-dialog-help";
      help.textContent = field.helpText;
      wrapper.appendChild(help);
    }

    appDialogFields.appendChild(wrapper);
  });
}

function collectDialogValues() {
  const values = {};
  const formData = new FormData(appDialogForm);
  for (const [key, value] of formData.entries()) {
    values[key] = typeof value === "string" ? value.trim() : value;
  }
  return values;
}

function showDialogError(message) {
  if (!appDialogError) {
    return;
  }
  appDialogError.textContent = message;
  appDialogError.hidden = false;
}

function clearDialogError() {
  if (!appDialogError) {
    return;
  }
  appDialogError.hidden = true;
  appDialogError.textContent = "";
}

function getFocusableElements() {
  return Array.from(appDialog?.querySelectorAll(FOCUSABLE_SELECTOR) ?? []).filter((element) => {
    return !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true";
  });
}

function trapFocus(event) {
  const focusable = getFocusableElements();
  if (focusable.length === 0) {
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function focusFirstField() {
  const initial = appDialog?.querySelector("[data-initial-focus='true']");
  if (initial instanceof HTMLElement) {
    initial.focus();
    if (typeof initial.select === "function") {
      initial.select();
    }
    return;
  }

  appDialogConfirm?.focus();
}

function closeDialog(result) {
  if (!activeDialogResolver) {
    return;
  }

  const resolver = activeDialogResolver;
  activeDialogResolver = null;
  activeDialogConfig = null;

  appDialog.hidden = true;
  clearDialogError();
  appDialogFields.innerHTML = "";

  const restoreTarget = lastFocusedElement;
  lastFocusedElement = null;
  if (restoreTarget instanceof HTMLElement) {
    restoreTarget.focus();
  }

  resolver(result);
}

export function closeActiveModal() {
  if (!appDialog?.hidden) {
    closeDialog(null);
    return true;
  }

  if (isHelpModalOpen) {
    showHelpModal(false);
    return true;
  }

  const mergeModal = document.getElementById("mergeModal");
  if (mergeModal?.classList.contains("visible")) {
    globalThis.closeMergeModal?.();
    return true;
  }

  return false;
}

export function showDialog({
  eyebrow = "",
  title,
  description = "",
  confirmLabel = "Continue",
  cancelLabel = "Cancel",
  showCancel = true,
  confirmVariant = "primary",
  fields = [],
  validate,
  dismissible = true,
}) {
  if (!appDialog || !appDialogForm) {
    throw new Error("App dialog is not initialized.");
  }

  if (activeDialogResolver) {
    closeDialog(null);
  }

  lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  activeDialogConfig = { validate, dismissible };

  appDialogEyebrow.textContent = eyebrow;
  appDialogEyebrow.hidden = !eyebrow;
  appDialogTitle.textContent = title;
  appDialogDescription.textContent = description;
  appDialogDescription.hidden = !description;
  appDialogConfirm.textContent = confirmLabel;
  appDialogConfirm.dataset.variant = confirmVariant;
  appDialogCancel.textContent = cancelLabel;
  appDialogCancel.hidden = !showCancel;
  renderDialogFields(fields);
  clearDialogError();
  appDialog.hidden = false;

  return new Promise((resolve) => {
    activeDialogResolver = resolve;
    requestAnimationFrame(() => {
      appDialogPanel?.focus();
      focusFirstField();
    });
  });
}

export async function confirmDialog(options) {
  const result = await showDialog({
    ...options,
    fields: [],
  });
  return Boolean(result);
}

export async function promptDialog(options) {
  const result = await showDialog(options);
  return result;
}

export async function alertDialog({
  title = "Heads up",
  description = "",
  confirmLabel = "OK",
  eyebrow = "",
}) {
  await showDialog({
    title,
    description,
    confirmLabel,
    eyebrow,
    showCancel: false,
    fields: [],
  });
}
