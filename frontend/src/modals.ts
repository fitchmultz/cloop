/**
 * modals.ts - Typed modal runtime shared by the shell and residual legacy UI.
 *
 * Purpose:
 *   Provide one TypeScript-owned modal implementation for help, confirm, alert,
 *   and prompt dialogs across the frontend runtime.
 *
 * Responsibilities:
 *   - Initialize and manage the shared help modal and app-dialog overlay.
 *   - Render typed dialog fields and collect validated form values.
 *   - Preserve focus, dismissal behavior, and keyboard trapping.
 *   - Expose a stable modal API that both TypeScript and residual legacy
 *     surfaces can share during the remaining frontend cutover.
 *
 * Scope:
 *   - Browser-only modal orchestration for frontend/index.html surfaces.
 *
 * Usage:
 *   - Imported by TypeScript UI modules directly.
 *   - Re-exported from frontend/src/legacy/modals.js for untouched legacy code.
 *
 * Invariants/Assumptions:
 *   - frontend/index.html preserves the shared app-dialog and help-modal DOM ids.
 *   - Only one prompt/confirm dialog is active at a time.
 *   - Merge-modal close requests are handled through a DOM event rather than
 *     inline window globals.
 */

const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

export const MERGE_MODAL_CLOSE_REQUEST_EVENT = "cloop:merge-modal-close-requested";

export interface DialogFieldOption {
  value: string;
  label: string;
}

export type DialogFieldType = "text" | "textarea" | "number" | "select" | "datetime-local";

export interface DialogFieldConfig {
  name: string;
  label: string;
  value?: string | undefined;
  required?: boolean | undefined;
  maxLength?: number | undefined;
  autocomplete?: string | undefined;
  placeholder?: string | undefined;
  type?: DialogFieldType | undefined;
  rows?: number | undefined;
  inputMode?: HTMLInputElement["inputMode"] | undefined;
  options?: DialogFieldOption[] | undefined;
  helpText?: string | undefined;
}

export interface DialogConfig {
  eyebrow?: string | undefined;
  title: string;
  description?: string | undefined;
  confirmLabel?: string | undefined;
  cancelLabel?: string | undefined;
  showCancel?: boolean | undefined;
  confirmVariant?: string | undefined;
  fields?: DialogFieldConfig[] | undefined;
  validate?: ((values: Record<string, string>) => string | null) | undefined;
  dismissible?: boolean | undefined;
}

export interface AlertDialogConfig {
  title?: string | undefined;
  description?: string | undefined;
  confirmLabel?: string | undefined;
  eyebrow?: string | undefined;
}

interface ModalElements {
  helpModal: HTMLElement | null;
  appDialog: HTMLElement | null;
  appDialogPanel: HTMLElement | null;
  appDialogForm: HTMLFormElement | null;
  appDialogEyebrow: HTMLElement | null;
  appDialogTitle: HTMLElement | null;
  appDialogDescription: HTMLElement | null;
  appDialogFields: HTMLElement | null;
  appDialogError: HTMLElement | null;
  appDialogCancel: HTMLButtonElement | null;
  appDialogConfirm: HTMLButtonElement | null;
}

interface ActiveDialogConfig {
  validate?: ((values: Record<string, string>) => string | null) | undefined;
  dismissible: boolean;
}

let elements: ModalElements | null = null;
let initialized = false;
let isHelpModalVisible = false;
let activeDialogResolver: ((result: Record<string, string> | null) => void) | null = null;
let activeDialogConfig: ActiveDialogConfig | null = null;
let lastFocusedElement: HTMLElement | null = null;

function canUseDom(): boolean {
  return typeof window !== "undefined" && typeof document !== "undefined";
}

function resolveElements(
  overrides: { helpModal?: HTMLElement | null; appDialog?: HTMLElement | null } = {},
): ModalElements {
  const helpModal = overrides.helpModal ?? document.getElementById("help-modal");
  const appDialog = overrides.appDialog ?? document.getElementById("app-dialog");
  return {
    helpModal,
    appDialog,
    appDialogPanel: appDialog?.querySelector<HTMLElement>(".app-dialog") ?? null,
    appDialogForm: document.getElementById("app-dialog-form") as HTMLFormElement | null,
    appDialogEyebrow: document.getElementById("app-dialog-eyebrow"),
    appDialogTitle: document.getElementById("app-dialog-title"),
    appDialogDescription: document.getElementById("app-dialog-description"),
    appDialogFields: document.getElementById("app-dialog-fields"),
    appDialogError: document.getElementById("app-dialog-error"),
    appDialogCancel: document.getElementById("app-dialog-cancel") as HTMLButtonElement | null,
    appDialogConfirm: document.getElementById("app-dialog-confirm") as HTMLButtonElement | null,
  };
}

function ensureInitialized(
  overrides: { helpModal?: HTMLElement | null; appDialog?: HTMLElement | null } = {},
): ModalElements {
  if (!canUseDom()) {
    throw new Error("Modal runtime is only available in the browser.");
  }

  if (!elements || overrides.helpModal !== undefined || overrides.appDialog !== undefined) {
    elements = resolveElements(overrides);
  }

  if (!initialized) {
    bindHandlers();
    initialized = true;
  }

  return elements;
}

function bindHandlers(): void {
  const current = elements;
  if (!current) {
    return;
  }

  current.helpModal?.addEventListener("click", (event) => {
    if (event.target === current.helpModal) {
      showHelpModal(false);
    }
  });

  current.helpModal
    ?.querySelector<HTMLElement>("[data-action='close-help']")
    ?.addEventListener("click", () => showHelpModal(false));

  current.appDialog?.addEventListener("click", (event) => {
    if (event.target === current.appDialog && activeDialogConfig?.dismissible !== false) {
      closeDialog(null);
    }
  });

  current.appDialogForm?.addEventListener("submit", (event) => {
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

  current.appDialog?.addEventListener("keydown", (event) => {
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
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    if (target.closest("[data-action='cancel-app-dialog'], [data-action='close-app-dialog']")) {
      closeDialog(null);
    }
  });
}

function renderDialogFields(fields: readonly DialogFieldConfig[]): void {
  const fieldsRoot = elements?.appDialogFields;
  if (!fieldsRoot) {
    return;
  }

  fieldsRoot.innerHTML = "";

  fields.forEach((field, index) => {
    const fieldId = `app-dialog-field-${field.name}`;
    const wrapper = document.createElement("label");
    wrapper.className = "app-dialog-field";
    wrapper.htmlFor = fieldId;

    const label = document.createElement("span");
    label.className = "app-dialog-label";
    label.textContent = field.label;
    wrapper.appendChild(label);

    let control: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
    if (field.type === "textarea") {
      const textarea = document.createElement("textarea");
      textarea.rows = field.rows ?? 4;
      control = textarea;
    } else if (field.type === "select") {
      const select = document.createElement("select");
      (field.options ?? []).forEach((option) => {
        const optionElement = document.createElement("option");
        optionElement.value = option.value;
        optionElement.textContent = option.label;
        if (option.value === field.value) {
          optionElement.selected = true;
        }
        select.appendChild(optionElement);
      });
      control = select;
    } else {
      const input = document.createElement("input");
      input.type = field.type ?? "text";
      control = input;
    }

    control.id = fieldId;
    control.name = field.name;
    control.className = "app-dialog-input";
    control.required = field.required ?? false;
    control.value = field.value ?? "";

    if (field.placeholder && "placeholder" in control) {
      control.placeholder = field.placeholder;
    }
    if (field.autocomplete && "autocomplete" in control) {
      control.autocomplete = field.autocomplete as AutoFill;
    }
    if (field.inputMode && control instanceof HTMLInputElement) {
      control.inputMode = field.inputMode;
    }
    if (field.maxLength && "maxLength" in control) {
      control.maxLength = field.maxLength;
    }
    if (index === 0) {
      control.dataset["initialFocus"] = "true";
    }

    wrapper.appendChild(control);

    if (field.helpText) {
      const help = document.createElement("span");
      help.className = "app-dialog-help";
      help.textContent = field.helpText;
      wrapper.appendChild(help);
    }

    fieldsRoot.appendChild(wrapper);
  });
}

function collectDialogValues(): Record<string, string> {
  const currentForm = elements?.appDialogForm;
  if (!currentForm) {
    return {};
  }

  const values: Record<string, string> = {};
  const formData = new FormData(currentForm);
  for (const [key, value] of formData.entries()) {
    values[key] = typeof value === "string" ? value.trim() : "";
  }
  return values;
}

function showDialogError(message: string): void {
  if (!elements?.appDialogError) {
    return;
  }
  elements.appDialogError.textContent = message;
  elements.appDialogError.hidden = false;
}

function clearDialogError(): void {
  if (!elements?.appDialogError) {
    return;
  }
  elements.appDialogError.hidden = true;
  elements.appDialogError.textContent = "";
}

function getFocusableElements(): HTMLElement[] {
  return Array.from(elements?.appDialog?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? []).filter((element) => {
    return !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true";
  });
}

function trapFocus(event: KeyboardEvent): void {
  const focusable = getFocusableElements();
  if (!focusable.length) {
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (!first || !last) {
    return;
  }

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function focusFirstField(): void {
  const initial = elements?.appDialog?.querySelector<HTMLElement>("[data-initial-focus='true']");
  if (initial) {
    initial.focus();
    if (initial instanceof HTMLInputElement || initial instanceof HTMLTextAreaElement) {
      initial.select();
    }
    return;
  }

  elements?.appDialogConfirm?.focus();
}

function closeDialog(result: Record<string, string> | null): void {
  if (!activeDialogResolver) {
    return;
  }

  const resolver = activeDialogResolver;
  activeDialogResolver = null;
  activeDialogConfig = null;

  if (elements?.appDialog) {
    elements.appDialog.hidden = true;
  }
  clearDialogError();
  if (elements?.appDialogFields) {
    elements.appDialogFields.innerHTML = "";
  }

  const restoreTarget = lastFocusedElement;
  lastFocusedElement = null;
  if (restoreTarget) {
    restoreTarget.focus();
  }

  resolver(result);
}

export function init(
  overrides: { helpModal?: HTMLElement | null; appDialog?: HTMLElement | null } = {},
): void {
  ensureInitialized(overrides);
}

export function showHelpModal(show: boolean): void {
  const current = ensureInitialized();
  if (!current.helpModal) {
    return;
  }

  if (show) {
    current.helpModal.classList.add("visible");
    current.helpModal.querySelector<HTMLElement>(".help-modal")?.focus();
    isHelpModalVisible = true;
    return;
  }

  current.helpModal.classList.remove("visible");
  isHelpModalVisible = false;
}

export function isModalOpen(): boolean {
  if (!canUseDom()) {
    return false;
  }
  ensureInitialized();
  return isHelpModalVisible
    || !Boolean(elements?.appDialog?.hidden ?? true)
    || Boolean(document.getElementById("mergeModal")?.classList.contains("visible"));
}

export function closeActiveModal(): boolean {
  if (!canUseDom()) {
    return false;
  }
  ensureInitialized();

  if (!elements?.appDialog?.hidden) {
    closeDialog(null);
    return true;
  }

  if (isHelpModalVisible) {
    showHelpModal(false);
    return true;
  }

  const mergeModal = document.getElementById("mergeModal");
  if (mergeModal?.classList.contains("visible")) {
    document.dispatchEvent(new CustomEvent(MERGE_MODAL_CLOSE_REQUEST_EVENT));
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
}: DialogConfig): Promise<Record<string, string> | null> {
  const current = ensureInitialized();
  if (!current.appDialog || !current.appDialogForm) {
    throw new Error("App dialog is not initialized.");
  }

  if (activeDialogResolver) {
    closeDialog(null);
  }

  lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  activeDialogConfig = { validate, dismissible };

  if (current.appDialogEyebrow) {
    current.appDialogEyebrow.textContent = eyebrow;
    current.appDialogEyebrow.hidden = !eyebrow;
  }
  if (current.appDialogTitle) {
    current.appDialogTitle.textContent = title;
  }
  if (current.appDialogDescription) {
    current.appDialogDescription.textContent = description;
    current.appDialogDescription.hidden = !description;
  }
  if (current.appDialogConfirm) {
    current.appDialogConfirm.textContent = confirmLabel;
    current.appDialogConfirm.dataset["variant"] = confirmVariant;
  }
  if (current.appDialogCancel) {
    current.appDialogCancel.textContent = cancelLabel;
    current.appDialogCancel.hidden = !showCancel;
  }

  renderDialogFields(fields);
  clearDialogError();
  current.appDialog.hidden = false;

  return new Promise((resolve) => {
    activeDialogResolver = resolve;
    requestAnimationFrame(() => {
      current.appDialogPanel?.focus();
      focusFirstField();
    });
  });
}

export async function confirmDialog(options: DialogConfig): Promise<boolean> {
  const result = await showDialog({
    ...options,
    fields: [],
  });
  return Boolean(result);
}

export async function promptDialog(options: DialogConfig): Promise<Record<string, string> | null> {
  return showDialog(options);
}

export async function alertDialog({
  title = "Heads up",
  description = "",
  confirmLabel = "OK",
  eyebrow = "",
}: AlertDialogConfig): Promise<void> {
  await showDialog({
    title,
    description,
    confirmLabel,
    eyebrow,
    showCancel: false,
    fields: [],
  });
}
