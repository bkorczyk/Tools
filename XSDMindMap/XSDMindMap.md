================================================================================
DOKUMENTACJA APLIKACJI: DYNAMICZNA MAPA MYŚLI XSD (FLASK + D3.JS)
================================================================================

1. OPIS PROGRAMU
--------------------------------------------------------------------------------
Interaktywna aplikacja webowa napisana w Pythonie i JavaScript (D3.js), 
służąca do wizualizacji struktury plików schematów XML (XSD) w formie 
dynamicznej mapy myśli. 

Aplikacja pozwala na wczytanie dowolnego pliku .xsd poprzez interfejs 
przeglądarki (metodą Drag & Drop lub wybiórczo z dysku), a następnie 
generuje wykreślane drzewo relacji od korzenia. Ze względu na wydajność 
i obsługę bardzo dużych schematów XSD, potomne węzły są doczytywane 
dynamicznie z backendu (podejście Lazy Loading) dopiero po kliknięciu 
w dany element.

2. WYMAGANIA WDROŻENIOWE
--------------------------------------------------------------------------------
- Środowisko: Python 3.10 lub nowszy
- Przeglądarka internetowa: Chrome, Edge, Firefox, Safari (obsługująca JavaScript ES6 i SVG)
- Wymagane biblioteki Python:
  * flask
  * xmlschema
  * standardowe: sys, io

Instalacja zależności:
  pip install flask xmlschema

3. ARCHITEKTURA I SKŁADANIA
--------------------------------------------------------------------------------
Aplikacja działa w modelu jednouzłowym (lokalny serwer webowy Flask + klient SPA):

Uruchomienie serwera:
  python XSDMindMap.py

Aplikacja automatycznie wystawia interfejs pod adresem:
  http://127.0.0.1:5000

P punkty końcowe API (Endpoints):
  POST /api/upload                Przesłanie i sparsowanie nowego pliku XSD z formy Drag & Drop.
  GET  /api/root                  Pobranie nazwy i właściwości głównego elementu (Root).
  GET  /api/children/<node_path>  Dynamiczne pobranie listy dzieci dla podanej ścieżki węzła.

4. ZASADA DZIAŁANIA
--------------------------------------------------------------------------------
1. Wczytanie pliku XSD:
   - Użytkownik przeciąga plik .xsd do okna przeglądarki lub wybiera go z dysku.
   - Plik przekazywany jest strumieniowo do backendu Flask (`/api/upload`) 
     i analizowany przez bibliotekę `xmlschema`.

2. Detekcja Węzła Głównego (Root):
   - Skrypt szuka elementu głównego w strukturze `schema.elements`. 
   - W przypadku braku elementów globalnych, automatycznie przeszukuje 
     typy złożone `schema.types` (np. dla specyficznych schematów typu TEAPPS).

3. Interaktywna Wizualizacja D3.js (Lazy Loading):
   - Inicjalnie wyrysowywany jest tylko węzeł główny.
   - Kliknięcie w węzeł posiadający dzieci wysyła żądanie AJAX do backendu 
     dla konkretnej ścieżki (np. `INVOICE/HEADER/ADDRESS`).
   - Drzewo rozwija się z płynną animacją przejścia, a pozycje węzłów 
     i powiązania przeliczane są dynamicznie.

5. PRZYKŁADY UŻYCIA
--------------------------------------------------------------------------------
a) Uruchomienie aplikacji:
   $ python XSDMindMap.py
   * Running on http://127.0.0.1:5000

b) Załadowanie pliku XSD:
   - Otwórz w przeglądarce http://127.0.0.1:5000.
   - Przeciągnij plik 'teappsxmlv30_schema_invoices.xsd' w obszar Drop Zone.

c) Nawigacja po strukturze:
   - Kliknij w niebieski punkt węzła, aby rozwinąć jego pod-elementy.
   - Użyj kółka myszy, aby przybliżać / oddalać (Zoom).
   - Chwyć i przeciągnij tło, aby przesuwać widok (Pan).
   - Kliknij przycisk 'Zmień plik XSD' w lewym górnym rogu, aby wczytać inny schemat.