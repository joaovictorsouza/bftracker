try {
  if (localStorage.getItem("theme") === "light") {
    document.documentElement.classList.remove("dark");
    document.querySelector('meta[name="theme-color"]').content = "#f4f5fb";
  }
} catch (_) {
  /* armazenamento indisponível */
}
