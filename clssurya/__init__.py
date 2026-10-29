__version__ = "0.0.1"

# Workaround for Frappe v16 bug where Document.__init__ calls init_valid_columns(),
# which in Meta populates the target doctype's fieldnames (e.g. 'process') into Meta.__dict__,
# shadowing Meta.process() method and causing "'NoneType' object is not callable".
try:
    from frappe.model.meta import Meta

    def _meta_init_valid_columns(self):
        pass

    Meta.init_valid_columns = _meta_init_valid_columns
except Exception:
    pass

