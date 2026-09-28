document.querySelector("#sessionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  const input = document.querySelector("#accessToken");
  const error = document.querySelector("#sessionError");
  button.disabled = true;
  error.textContent = "";
  try {
    // 口令仅放在请求正文中，由服务端签发 HttpOnly 会话 Cookie。
    // Send the token only in the request body; the server issues an HttpOnly session cookie.
    const response = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: input.value }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "暂时无法进入工具");
    input.value = "";
    window.location.replace("/");
  } catch (failure) {
    error.textContent = failure.message;
  } finally {
    button.disabled = false;
  }
});
