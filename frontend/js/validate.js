/**
 * FitCore — Client-Side Form Validation Library
 *
 * Provides reusable validation functions, real-time field-level feedback,
 * and form-level validation for all frontend forms.
 *
 * Usage:
 *   1. Include <script src="js/validate.js"></script> after api.js
 *   2. Call initFormValidation(formEl) on any <form> to auto-validate on submit
 *   3. Call initFieldValidation(inputEl, rules) for individual fields
 *   4. Use validate.email(val), validate.required(val), etc. for standalone checks
 */

const validate = {
  /** Returns true if value is empty (null, undefined, or whitespace-only string) */
  isEmpty(val) {
    return val == null || (typeof val === 'string' && val.trim() === '');
  },

  /** Required field — non-empty */
  required(val, fieldName = 'This field') {
    if (this.isEmpty(val)) return `${fieldName} is required.`;
    return null;
  },

  /** Email format */
  email(val) {
    if (this.isEmpty(val)) return null; // use required() for mandatory
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!re.test(val)) return 'Please enter a valid email address.';
    return null;
  },

  /** Phone: exactly 10 digits (Nepal format) */
  phone(val) {
    if (this.isEmpty(val)) return null;
    const cleaned = val.replace(/\D/g, '');
    if (cleaned.length !== 10) return 'Phone number must be exactly 10 digits.';
    return null;
  },

  /** Minimum length */
  minLength(val, min, fieldName = 'This field') {
    if (this.isEmpty(val)) return null;
    if (val.length < min) return `${fieldName} must be at least ${min} characters.`;
    return null;
  },

  /** Maximum length */
  maxLength(val, max, fieldName = 'This field') {
    if (this.isEmpty(val)) return null;
    if (val.length > max) return `${fieldName} must be at most ${max} characters.`;
    return null;
  },

  /** Password strength: min 8 chars, at least one letter and one number */
  password(val) {
    if (this.isEmpty(val)) return null;
    if (val.length < 8) return 'Password must be at least 8 characters.';
    if (!/[A-Za-z]/.test(val)) return 'Password must contain at least one letter.';
    if (!/[0-9]/.test(val)) return 'Password must contain at least one number.';
    return null;
  },

  /** Password confirmation match */
  passwordMatch(val, otherVal) {
    if (this.isEmpty(val) || this.isEmpty(otherVal)) return null;
    if (val !== otherVal) return 'Passwords do not match.';
    return null;
  },

  /** Numeric value */
  numeric(val, fieldName = 'This field') {
    if (this.isEmpty(val)) return null;
    if (isNaN(Number(val))) return `${fieldName} must be a number.`;
    return null;
  },

  /** Minimum numeric value */
  min(val, minVal, fieldName = 'This field') {
    if (this.isEmpty(val)) return null;
    const num = Number(val);
    if (isNaN(num) || num < minVal) return `${fieldName} must be at least ${minVal}.`;
    return null;
  },

  /** Date must not be in the future */
  notFuture(val, fieldName = 'This field') {
    if (this.isEmpty(val)) return null;
    const date = new Date(val);
    const today = new Date();
    today.setHours(23, 59, 59, 999);
    if (date > today) return `${fieldName} cannot be in the future.`;
    return null;
  },

  /** Date must not be in the past */
  notPast(val, fieldName = 'This field') {
    if (this.isEmpty(val)) return null;
    const date = new Date(val);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (date < today) return `${fieldName} cannot be in the past.`;
    return null;
  },
};

/**
 * Show an error message under a field and mark it invalid.
 * @param {HTMLElement} field - The input element
 * @param {string} message - Error message to display
 */
function showFieldError(field, message) {
  // Remove existing error
  clearFieldError(field);

  field.classList.add('is-invalid');
  field.classList.remove('is-valid');

  const feedback = document.createElement('div');
  feedback.className = 'invalid-feedback';
  feedback.textContent = message;
  feedback.style.display = 'block';
  field.parentNode.appendChild(feedback);
}

/**
 * Mark a field as valid.
 * @param {HTMLElement} field - The input element
 */
function showFieldValid(field) {
  clearFieldError(field);
  if (!field.hasAttribute('required') && validate.isEmpty(field.value)) {
    // Don't mark optional empty fields as valid
    return;
  }
  field.classList.remove('is-invalid');
  field.classList.add('is-valid');
}

/**
 * Clear any error/valid state from a field.
 * @param {HTMLElement} field - The input element
 */
function clearFieldError(field) {
  field.classList.remove('is-invalid', 'is-valid');
  const existingFeedback = field.parentNode.querySelector('.invalid-feedback');
  if (existingFeedback) existingFeedback.remove();
}

/**
 * Validate a single field against its rules and show feedback.
 * @param {HTMLElement} field - The input element
 * @param {Array<Function>} rules - Array of validator functions that return error string or null
 * @returns {string|null} First error message or null if valid
 */
function validateField(field, rules) {
  const value = field.type === 'checkbox' ? field.checked : field.value;
  for (const rule of rules) {
    const error = rule(value);
    if (error) {
      showFieldError(field, error);
      return error;
    }
  }
  showFieldValid(field);
  return null;
}

/**
 * Validate an entire form. Shows errors on each invalid field.
 * @param {HTMLFormElement} formEl - The form element
 * @param {Object} fieldRules - Map of field name/id to array of validator functions
 * @returns {boolean} True if all fields are valid
 */
function validateForm(formEl, fieldRules) {
  let firstInvalid = null;
  let allValid = true;

  for (const [fieldName, rules] of Object.entries(fieldRules)) {
    const field = formEl.querySelector(`[name="${fieldName}"], #${fieldName}`);
    if (!field) continue;
    const error = validateField(field, rules);
    if (error && !firstInvalid) {
      firstInvalid = field;
      allValid = false;
    }
  }

  if (firstInvalid) {
    firstInvalid.focus();
  }

  return allValid;
}

/**
 * Set up real-time validation on a field (on input/blur).
 * @param {HTMLElement} field - The input element
 * @param {Array<Function>} rules - Array of validator functions
 */
function initFieldValidation(field, rules) {
  const handler = () => validateField(field, rules);
  field.addEventListener('input', handler);
  field.addEventListener('blur', handler);
}

/**
 * Set up a form with real-time validation and submit-time validation.
 * @param {HTMLFormElement} formEl - The form element
 * @param {Object} fieldRules - Map of field name/id to array of validator functions
 * @param {Function} onSubmit - Async function called when form is valid (receives form element)
 */
function initFormValidation(formEl, fieldRules, onSubmit) {
  // Set up real-time validation for each field
  for (const [fieldName, rules] of Object.entries(fieldRules)) {
    const field = formEl.querySelector(`[name="${fieldName}"], #${fieldName}`);
    if (field) initFieldValidation(field, rules);
  }

  // Validate on submit
  formEl.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(formEl, fieldRules)) return;
    if (onSubmit) await onSubmit(formEl);
  });
}
