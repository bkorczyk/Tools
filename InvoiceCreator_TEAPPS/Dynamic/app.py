import win32gui

# Nazwa okna lub szukanie po klasie/tytule
# Najlepiej podglądnąć okno np. za pomocą WinSpy, ale możesz też spróbować pobrać tekst z fokusu:

hwnd = win32gui.GetFocus()  # Pobiera uchwyt aktualnie zaznaczonego elementu (fokusu)
length = win32gui.SendMessage(hwnd, 0x000E, 0, 0)  # WM_GETTEXTLENGTH
buf = win32gui.PyMakeBuffer(length + 1)
win32gui.SendMessage(hwnd, 0x000D, length + 1, buf)  # WM_GETTEXT
password = buf[:length].tobytes().decode("utf-16" if "unicode" in str(type(buf)) else "ansi", errors="ignore")

print(f"Odzyskany tekst: {password}")