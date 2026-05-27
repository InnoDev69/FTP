document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("loginForm");
  const errorBox = document.getElementById("loginError");
  const submitBtn = document.getElementById("loginSubmit");

  if (!form) {
    return;
  }

  const setError = (message) => {
    if (!errorBox) {
      return;
    }
    if (!message) {
      errorBox.textContent = "";
      errorBox.hidden = true;
      return;
    }
    errorBox.textContent = message;
    errorBox.hidden = false;
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setError("");

    const formData = new FormData(form);
    const username = (formData.get("username") || "").trim();
    const password = formData.get("password") || "";

    if (!username || !password) {
      setError("Completa usuario y contrasena");
      return;
    }

    submitBtn.disabled = true;
    const originalLabel = submitBtn.textContent;
    submitBtn.textContent = "Ingresando...";

    try {
      await AjaxManager.post("/api/login", { username, password });
      window.location.href = "/";
    } catch (err) {
      setError(err.message || "No se pudo iniciar sesion");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = originalLabel;
    }
  });
});
