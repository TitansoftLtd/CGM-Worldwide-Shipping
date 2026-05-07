frappe.ui.form.on("Task", {
    onload: function(frm) {
        frm.set_query("department", function() {
            return {
                filters: {
                    parent_department: ["like", "Operations%"]
                }
            };
        });
    }
});