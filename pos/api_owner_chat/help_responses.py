HELP_TOPICS = {
    "tambah_produk": {
        "title": "Cara tambah produk",
        "text": (
            "🧾 Cara tambah produk:\n"
            "1) Buka menu Produk\n"
            "2) Klik tombol ➕ Tambah\n"
            "3) Isi: Nama, Barcode (Code), SKU (opsional), Harga Jual, Stok\n"
            "4) Pilih Kategori & Unit\n"
            "5) Simpan\n\n"
            "Tips:\n"
            "• Barcode wajib unik\n"
            "• SKU opsional (untuk internal)\n"
            "• Pastikan harga beli (buy_price) terisi agar margin akurat"
        ),
    },
    "retur_barang": {
        "title": "Cara retur barang",
        "text": (
            "🧾 Cara retur barang (Sale Return):\n"
            "1) Buka menu Retur / Product Return\n"
            "2) Pilih invoice / order terkait\n"
            "3) Pilih item dan qty yang diretur\n"
            "4) Isi catatan (opsional)\n"
            "5) Simpan\n\n"
            "Catatan:\n"
            "• Sistem akan menambah stok jika return diproses sebagai SALE_RETURN\n"
            "• Pastikan retur tidak melebihi qty terjual"
        ),
    },
    "cetak_struk": {
        "title": "Cara cetak struk",
        "text": (
            "🧾 Cara cetak struk:\n"
            "1) Selesaikan transaksi (PAID)\n"
            "2) Pastikan printer thermal sudah pairing & connect\n"
            "3) Klik Print / Cetak Struk\n\n"
            "Jika gagal:\n"
            "• Cek Bluetooth permission (Android 12+ perlu BLUETOOTH_CONNECT)\n"
            "• Re-pair printer dan coba lagi\n"
            "• Pastikan ukuran kertas (58mm/80mm) sesuai setting"
        ),
    },
    "tambah_kategori": {
        "title": "Cara tambah kategori",
        "text": (
            "🏷️ Cara tambah kategori:\n"
            "1) Buka menu Kategori\n"
            "2) Klik ➕ Tambah\n"
            "3) Isi nama kategori\n"
            "4) Upload icon (opsional)\n"
            "5) Simpan"
        ),
    },
    "tambah_supplier": {
        "title": "Cara tambah supplier",
        "text": (
            "🚚 Cara tambah supplier:\n"
            "1) Buka menu Supplier\n"
            "2) Klik ➕ Tambah\n"
            "3) Isi: nama, contact person, phone, email, alamat\n"
            "4) Simpan"
        ),
    },
    "stok_opname": {
        "title": "Cara stok opname",
        "text": (
            "📦 Cara stok opname (Inventory Count):\n"
            "1) Buka menu Inventory Count\n"
            "2) Buat Count baru\n"
            "3) Isi counted_stock untuk setiap produk\n"
            "4) Simpan\n\n"
            "Opsional:\n"
            "• Buat Adjustment otomatis berdasarkan selisih (difference)\n"
            "• Catat alasan selisih (lost/damage/correction)"
        ),
    },
}

HELP_FALLBACK_TEXT = (
    "🧾 Help POS\n"
    "Contoh yang bisa ditanya:\n"
    "• cara tambah produk\n"
    "• cara retur barang\n"
    "• cara cetak struk\n"
    "• cara tambah kategori\n"
    "• cara tambah supplier\n"
    "• cara stok opname"
)