E2E Test Checklist — Gangguan Penyulang 20 kV (3 Phasa)

Tujuan:
Memastikan alur Input → Database → Gangguan Aktif → Riwayat → Telegram → Laporan Bulanan
sudah konsisten untuk arus R/S/T sebelum, setelah, termanuver, sisa beban, durasi, dan ENS.

Data Dasar Uji

Gunakan satu GI/Penyulang TEST yang memang boleh dipakai untuk pengujian.

Parameter dasar:

Tegangan sebelum: 20 kV

Power Factor: 0.85

Arus sebelum:

R = 120 A

S = 110 A

T = 100 A

Rata-rata legacy yang diharapkan = 110 A

Untuk test yang membutuhkan arus setelah:

R = 115 A

S = 108 A

T = 102 A

Rata-rata legacy setelah = 108.333 A

Catatan:
Jangan lakukan test pada periode bulanan yang sudah APPROVED.
Gunakan tanggal pengujian yang masih DRAFT / belum memiliki laporan approved.

TEST 1 — BELUM TERSUPLAI

Input

Jenis: Gangguan

PMT: Trip

Waktu gangguan: 10:00

Supply Status: BELUM

Arus sebelum: 120 / 110 / 100 A

Tegangan: 20 kV

PF: 0.85

Expected Database

load_current_before_r_a = 120

load_current_before_s_a = 110

load_current_before_t_a = 100

load_current_before_a = 110

maneuvered_current_r/s/t_a = NULL

maneuvered_current_a = NULL

remaining_current_r_a = 120

remaining_current_s_a = 110

remaining_current_t_a = 100

remaining_current_a = 110

ens_kwh = NULL

customer_outage_duration_min = NULL

record_status = ONGOING

Expected UI

Gangguan Aktif:

Menampilkan Arus Sebelum R/S/T.

Status Suplai = Belum Tersuplai.

ENS berjalan bertambah sesuai waktu berjalan.

Telegram:

Arus Sebelum tampil R/S/T.

Belum ada bagian pemulihan.

TEST 2 — FEEDER ASAL

Input

Waktu gangguan: 10:00

Supply Status: FEEDER_ASAL

Mulai tersuplai: 10:30

Arus sebelum: 120 / 110 / 100 A

Tegangan: 20 kV

PF: 0.85

Arus setelah: 115 / 108 / 102 A

Expected Database

Avg sebelum = 110 A

maneuvered R/S/T = 0 / 0 / 0 A

maneuvered avg = 0 A

remaining R/S/T = 0 / 0 / 0 A

remaining avg = 0 A

customer_outage_duration_min = 30

outage_duration_min = 30

ens_kwh ≈ 1619.468

load_current_after_a ≈ 108.333

Expected UI

Riwayat:

Arus Sebelum R/S/T benar.

Arus Setelah R/S/T benar.

Tidak perlu menampilkan Beban Termanuver sebagai nilai operasional utama.

Telegram:

Status Suplai = FEEDER_ASAL.

Arus Setelah R/S/T benar.

TEST 3 — MANUVER PENUH

Input

Waktu gangguan: 10:00

Supply Status: MANUVER_PENUH

Mulai tersuplai: 10:30

Arus sebelum: 120 / 110 / 100 A

Tegangan: 20 kV

PF: 0.85

Arus setelah: 115 / 108 / 102 A

Expected Database

Avg sebelum = 110 A

Termanuver:

R = 120

S = 110

T = 100

Avg = 110

Sisa:

R = 0

S = 0

T = 0

Avg = 0

Durasi = 30 menit

ENS ≈ 1619.468 kWh

Avg arus setelah ≈ 108.333 A

Expected UI

Gangguan Aktif / Riwayat:

Beban Termanuver tampil R/S/T.

Sisa tidak perlu ditonjolkan karena 0.

Arus Setelah tampil R/S/T.

Telegram:

Beban Termanuver tampil R/S/T.

Arus Setelah tampil R/S/T.

Laporan:

Termanuver R/S/T tersedia.

Menit tetap tersedia.

TEST 4 — MANUVER SEBAGIAN

Input

Waktu gangguan: 10:00

Supply Status: MANUVER_SEBAGIAN

Mulai tersuplai sebagian: 10:30

Final normalisasi: 11:30

Arus sebelum:

R = 120

S = 110

T = 100

Termanuver:

R = 80

S = 70

T = 60

Tegangan: 20 kV

PF: 0.85

Arus setelah:

R = 115

S = 108

T = 102

Expected Database

Arus sebelum:

R/S/T = 120 / 110 / 100

Avg = 110

Termanuver:

R/S/T = 80 / 70 / 60

Avg = 70

Sisa otomatis:

R = 40

S = 40

T = 40

Avg = 40

Durasi:

Interval 1 = 30 menit

Interval 2 = 60 menit

Customer outage duration = 90 menit

ENS:

ENS final ≈ 2797.262 kWh

Arus setelah:

R/S/T = 115 / 108 / 102

Avg ≈ 108.333

Expected UI

Gangguan Aktif:

Beban Termanuver R/S/T.

Sisa Beban R/S/T.

ENS berjalan sesuai sisa beban jika belum final.

Riwayat:

Termanuver R/S/T.

Sisa R/S/T.

Arus Setelah R/S/T.

Durasi 90 menit.

ENS ≈ 2797.262 kWh.

Telegram:

Beban Termanuver R/S/T.

Sisa Beban R/S/T.

Arus Setelah R/S/T.

Laporan Bulanan:

Status Suplai.

Termanuver R/S/T.

Sisa R/S/T.

Arus Setelah R/S/T.

MENIT = 90.

ENS ≈ 2797.262 kWh.

SQL VERIFIKASI PER EVENT

Ganti <EVENT_ID> dengan Event ID dari aplikasi.

select
    event_id,
    event_type_code,
    event_date,
    event_time,
    supply_status_code,

    load_current_before_r_a,
    load_current_before_s_a,
    load_current_before_t_a,
    load_current_before_a,

    maneuvered_current_r_a,
    maneuvered_current_s_a,
    maneuvered_current_t_a,
    maneuvered_current_a,

    remaining_current_r_a,
    remaining_current_s_a,
    remaining_current_t_a,
    remaining_current_a,

    supply_restored_date,
    supply_restored_time,

    final_supply_normalized,
    final_supply_normalization_date,
    final_supply_normalization_time,

    recovery_status_code,
    recovery_date,
    recovery_time,

    load_current_after_r_a,
    load_current_after_s_a,
    load_current_after_t_a,
    load_current_after_a,

    customer_outage_duration_min,
    outage_duration_min,
    pmt_condition_duration_min,
    ens_kwh,
    record_status
from public.trx_kejadian_penyulang
where event_id = '<EVENT_ID>'::uuid;

KRITERIA LULUS FINAL

Semua test dinyatakan PASS jika:

R/S/T tersimpan benar.

Legacy average sesuai rata-rata R/S/T.

Sisa beban dihitung otomatis dan benar.

ENS sesuai status pemulihan.

Gangguan Aktif konsisten.

Riwayat konsisten.

Telegram konsisten.

Excel/PDF konsisten.

Event yang bulanannya APPROVED tidak dapat diedit.