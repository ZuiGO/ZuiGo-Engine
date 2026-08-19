from bs4 import BeautifulSoup
html = """
<html>
<body>
  <header><img src="logo.png" alt="logo"></header>
  <main>
    <img src="hero.jpg" alt="hero">
  </main>
</body>
</html>
"""
soup = BeautifulSoup(html, "html.parser")
# find first img not in header or nav
img = None
for i in soup.find_all("img"):
    if not i.find_parent(["header", "nav", "footer"]):
        img = i
        break
print(img)
