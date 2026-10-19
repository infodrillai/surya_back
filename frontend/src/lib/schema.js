import { z } from 'zod';

const NUMERIC = ['number', 'currency', 'percent'];

/** @param {object} f field config */

function fieldSchema(f) {
  if (NUMERIC.includes(f.type)) {
    let s = z.preprocess(
      (value) => {
        if (value === '' || value === null || value === undefined) {
          if (f.default) return f.default();

          // Empty optional numeric fields default to zero.
          // Positive fields must still have a value greater than zero.
          if (f.positive || f.required) return undefined;

          return 0;
        }

        return value;
      },
      z.coerce.number({ invalid_type_error: 'Enter a number' })
    );

    if (f.positive) {
      s = s.pipe(z.number().gt(0, 'Must be greater than 0'));
    } else if (!f.allowNegative) {
      s = s.pipe(z.number().min(0, 'Cannot be negative'));
    }

    if (f.max != null) {
      s = s.pipe(z.number().max(f.max, `Max ${f.max}`));
    }

    if (f.default) {
      s = s.default(() => f.default());
    }

    return s;
  }

  if (f.type === 'check') return z.coerce.number();

  const str = z.string();

  return z.preprocess(
    (v) => (v == null ? '' : String(v)),
    f.required ? str.min(1, 'Required') : str
  );
}


/** Builds a Zod schema from a resource config (fields + child tables + optional cross-field validate). */
export function buildSchema(config) {
  const shape = {};
  config.fields.forEach((f) => (shape[f.name] = fieldSchema(f)));
  (config.tables || []).forEach((t) => {
    const row = {};
    t.fields.forEach((f) => (row[f.name] = fieldSchema(f)));
    shape[t.name] = z.array(z.object(row).passthrough());
  });
  return z.object(shape).passthrough().superRefine((v, ctx) => {
    const errs = config.validate?.(v) || {};
    Object.entries(errs).forEach(([path, message]) => ctx.addIssue({ code: 'custom', path: path.split('.'), message }));
  });
}

/** Default form values for a new or existing document. */
export function buildDefaults(config, doc) {
  const out = { ...(doc || {}) };
  config.fields.forEach((f) => {
    if (out[f.name] == null) {
      const def = typeof f.default === 'function' ? f.default() : f.default;
      out[f.name] = def ?? (f.type === 'check' || NUMERIC.includes(f.type) ? (f.type === 'check' ? 0 : '') : '');
    }
  });
  (config.tables || []).forEach((t) => {
    out[t.name] = (doc?.[t.name] || []).map((r) => {
      const row = { ...r };

      t.fields.forEach((f) => {
        if (row[f.name] == null || row[f.name] === '') {
          row[f.name] = f.default?.() ??
            (f.type === 'check' || NUMERIC.includes(f.type)
              ? (f.type === 'check' ? 0 : 0)
              : '');
        }
      });

      return row;
    });
  });
  return out;
}

/** Remove react-hook-form helper keys before sending to Frappe. */
export function cleanPayload(values) {
  const strip = (o) =>
    Array.isArray(o) ? o.map(strip) : o && typeof o === 'object' ? Object.fromEntries(Object.entries(o).filter(([k]) => k !== '_key').map(([k, v]) => [k, strip(v)])) : o;
  return strip(values);
}
