# Product Requirements Document (PRD)
# Ngulik

**Version:** 0.1.0  
**Status:** Draft  
**Product Type:** Local-first NLP / Social Listening & Text Intelligence System  
**Primary Language:** Bahasa Indonesia  
**Target Environment:** Local Development  
**Document Owner:** Project Team

---

## 1. Product Overview

### 1.1 Nama Produk

**Ngulik**

Ngulik adalah sistem berbasis **Natural Language Processing (NLP)** yang dirancang untuk mengumpulkan, mengolah, dan menganalisis kumpulan komentar atau teks publik dari sumber internet yang tersedia secara sah, kemudian menemukan pola bahasa, keyword, frasa, dan topik yang muncul secara dominan.

Sistem menggunakan pendekatan **iterative keyword discovery**, yaitu memulai proses dengan sejumlah seed keyword, mengumpulkan data berdasarkan keyword tersebut, menganalisis data yang terkumpul, kemudian menghasilkan kandidat keyword baru untuk memperluas proses pengumpulan data.

### 1.2 Problem Statement

Data komentar publik di internet memiliki volume besar dan memiliki karakteristik:

- tidak terstruktur;
- mengandung slang dan variasi ejaan;
- mengandung spam dan duplikasi;
- memiliki konteks yang berbeda-beda;
- menggunakan kata atau istilah yang dapat berkembang dari waktu ke waktu;
- sulit dianalisis secara manual dalam jumlah besar.

Penggunaan keyword statis juga memiliki keterbatasan. Sistem hanya akan menemukan data yang sesuai dengan keyword yang sudah diketahui sebelumnya.

Karena itu diperlukan sistem yang mampu:

1. menggunakan seed keyword sebagai titik awal;
2. mengumpulkan data teks dari sumber yang tersedia;
3. membersihkan dan menormalisasi data;
4. menemukan kata dan frasa yang sering muncul;
5. menemukan hubungan antarkata;
6. menghasilkan kandidat keyword baru;
7. memungkinkan proses tersebut dilakukan secara iteratif.

### 1.3 Product Vision

Membangun **local-first text intelligence platform** yang mampu mengubah kumpulan komentar publik yang tidak terstruktur menjadi informasi terstruktur mengenai:

- keyword;
- frasa;
- pola kemunculan kata;
- hubungan antarkata;
- cluster/topik;
- perkembangan keyword dari iterasi ke iterasi.

---

# 2. Goals & Objectives

## 2.1 Primary Goals

Sistem harus mampu:

1. menerima seed keyword;
2. mengumpulkan data teks dari sumber yang didukung;
3. menyimpan raw data secara terstruktur;
4. membersihkan dan menormalisasi teks;
5. menghapus atau menandai data duplikat dan spam;
6. melakukan frequency analysis;
7. melakukan n-gram analysis;
8. melakukan TF-IDF analysis;
9. melakukan co-occurrence analysis;
10. menghasilkan kandidat keyword baru;
11. melakukan iterasi keyword discovery;
12. menyediakan hasil analisis yang dapat dibaca manusia.

## 2.2 Secondary Goals

Pada tahap pengembangan berikutnya sistem dapat:

- menggunakan semantic embeddings;
- melakukan clustering;
- menggunakan local LLM melalui Ollama;
- mengelompokkan topik secara otomatis;
- menyediakan dashboard interaktif;
- mendukung banyak sumber;
- menjalankan collection secara terjadwal;
- melakukan analisis temporal.

## 2.3 Non-Goals

Versi MVP tidak bertujuan untuk:

- melakukan surveillance terhadap individu;
- mengidentifikasi atau membuat profil personal pengguna;
- mengumpulkan data pribadi yang tidak diperlukan;
- melakukan deanonymization;
- memprediksi identitas seseorang;
- melakukan manipulasi opini publik;
- melakukan automated engagement;
- mengirim komentar/postingan;
- melakukan spam;
- mengumpulkan seluruh data dari seluruh internet;
- menjamin representasi seluruh populasi masyarakat.

---

# 3. Target Users

## 3.1 Primary User

### Researcher / Developer

Pengguna teknis yang ingin:

- melakukan eksplorasi data teks;
- mempelajari NLP;
- menemukan pola bahasa;
- mengembangkan sistem social listening;
- mengembangkan dataset penelitian.

## 3.2 Secondary User

### Analyst

Pengguna yang membutuhkan:

- keyword trends;
- topic discovery;
- frequency analysis;
- relationship antar-keyword;
- ringkasan pola teks.

---

# 4. Core Concept

Sistem menggunakan pendekatan:

```text
Seed Keywords
      ↓
Data Collection
      ↓
Raw Data Storage
      ↓
Data Cleaning
      ↓
Text Processing
      ↓
Keyword Discovery
      ↓
Candidate Keywords
      ↓
Human Review
      ↓
Approved Keywords
      ↓
Data Collection
      ↓
Iteration
```

Konsep utama ini disebut:

**Iterative Keyword Expansion / Keyword Discovery Pipeline**

---

# 5. Product Scope

## 5.1 MVP Scope

MVP harus mencakup:

### Input

- seed keyword;
- phrase;
- hashtag;
- sumber data;
- parameter collection.

### Collection

- collector abstraction;
- minimal satu sumber data;
- penyimpanan raw data.

### Processing

- normalization;
- tokenization;
- stopword filtering;
- duplicate detection;
- basic spam filtering.

### Analysis

- word frequency;
- n-gram;
- TF-IDF;
- co-occurrence.

### Discovery

- candidate keyword generation;
- candidate scoring;
- candidate review;
- keyword approval/rejection.

### Storage

- raw comments;
- cleaned comments;
- keywords;
- candidate keywords;
- analysis results;
- collection metadata.

---

# 6. Functional Requirements

## FR-001 Seed Keyword Management

Sistem harus memungkinkan pengguna:

- menambahkan seed keyword;
- menghapus keyword;
- mengubah keyword;
- mengelompokkan keyword;
- menentukan tipe keyword.

Jenis keyword:

```text
KEYWORD
PHRASE
HASHTAG
```

Contoh struktur:

```yaml
keywords:
  - keyword_a
  - keyword_b

phrases:
  - "frasa tertentu"

hashtags:
  - "#contoh"
```

---

## FR-002 Data Collection

Sistem harus memiliki abstraction layer untuk collector.

```text
Collector Interface
        │
 ┌──────┼──────┐
 ↓      ↓      ↓
Source A Source B Source C
```

Setiap collector harus menghasilkan schema data yang seragam.

Contoh:

```json
{
  "source": "example",
  "source_id": "12345",
  "text": "example comment",
  "author_id": null,
  "created_at": "2026-09-20T10:00:00",
  "url": "..."
}
```

Data identitas pengguna tidak boleh dikumpulkan jika tidak diperlukan oleh tujuan analisis.

---

## FR-003 Raw Data Storage

Sistem harus menyimpan raw text sebelum proses cleaning.

Tujuannya:

- audit pipeline;
- debugging;
- reprocessing;
- membandingkan hasil preprocessing;
- menghindari kebutuhan collection ulang.

Raw data harus dipisahkan dari cleaned data.

---

## FR-004 Data Cleaning

Sistem harus menyediakan preprocessing pipeline:

```text
Raw Text
   ↓
Unicode Normalization
   ↓
Lowercase
   ↓
URL Handling
   ↓
Mention Handling
   ↓
Whitespace Normalization
   ↓
Slang Normalization
   ↓
Tokenization
   ↓
Stopword Filtering
   ↓
Duplicate Detection
   ↓
Clean Text
```

Cleaning harus dapat dikonfigurasi.

Sistem tidak boleh menghapus informasi secara permanen dari raw dataset.

---

## FR-005 Duplicate Detection

Sistem harus mendeteksi:

### Exact Duplicate

Komentar yang memiliki teks identik.

### Near Duplicate

Komentar yang sangat mirip tetapi memiliki sedikit perubahan.

Contoh:

```text
"ini lucu banget"

"ini lucu banget wkwk"
```

Metode dapat dikembangkan menggunakan:

- normalized text comparison;
- hashing;
- similarity score.

---

# 7. Keyword Discovery

## 7.1 Frequency Analysis

Sistem menghitung frekuensi:

```text
Term
Frequency
Relative Frequency
```

Output:

```text
TERM          FREQUENCY
-----------------------
term_a        1,203
term_b          982
term_c          745
```

Stopwords tidak dihitung sebagai keyword utama.

---

## 7.2 N-Gram Analysis

Sistem harus mendukung:

- unigram;
- bigram;
- trigram.

Contoh:

```text
Unigram:
kata_a

Bigram:
kata_a kata_b

Trigram:
kata_a kata_b kata_c
```

N-gram digunakan untuk menemukan frasa yang sering muncul.

---

## 7.3 TF-IDF

Sistem menggunakan TF-IDF untuk menemukan istilah yang relatif khas pada dokumen atau cluster tertentu.

Output minimum:

```text
term
tf
idf
tfidf_score
```

---

## 7.4 Co-occurrence Analysis

Sistem menghitung hubungan kemunculan dua istilah dalam konteks yang sama.

Contoh:

```text
keyword_a
    │
    ├── term_x
    ├── term_y
    └── term_z
```

Metrik dapat berupa:

- raw co-occurrence;
- normalized co-occurrence;
- association score.

---

# 8. Candidate Keyword Generation

Kandidat keyword dapat berasal dari:

```text
Frequency
    +
N-Gram
    +
TF-IDF
    +
Co-occurrence
```

Contoh:

```text
Candidate
-----------------
term_x
term_y
term_z
phrase_a
phrase_b
```

Setiap kandidat harus memiliki metadata:

```text
term
source_method
frequency
score
discovered_from
iteration
status
```

Status:

```text
PENDING
APPROVED
REJECTED
```

---

# 9. Human-in-the-Loop

Sistem tidak boleh otomatis memasukkan seluruh kandidat ke seed keyword.

Pengguna harus dapat melakukan review:

```text
Candidate Keyword
        ↓
     Review
    /       \
Approve    Reject
   ↓
 Seed      Ignore
```

Hal ini diperlukan karena kata yang sering muncul belum tentu relevan.

---

# 10. Iteration System

Setiap proses discovery memiliki nomor iterasi.

Contoh:

```text
Iteration 0
Seed:
A, B, C

        ↓

Iteration 1
Discovered:
D, E, F

        ↓

Iteration 2
Discovered:
G, H, I
```

Sistem harus menyimpan hubungan:

```text
keyword D
discovered_from = keyword A
iteration = 1
```

Dengan demikian pengguna dapat menelusuri asal sebuah keyword.

---

# 11. Data Model

## 11.1 keywords

```text
id
term
type
status
created_at
updated_at
```

## 11.2 comments

```text
id
source
source_id
text_raw
created_at
collected_at
```

## 11.3 cleaned_comments

```text
id
comment_id
text_clean
language
is_duplicate
is_spam
processed_at
```

## 11.4 collection_runs

```text
id
source
started_at
finished_at
keyword_count
comments_collected
status
```

## 11.5 keyword_candidates

```text
id
term
source_method
frequency
score
discovered_from
iteration
status
created_at
```

---

# 12. System Architecture

MVP:

```text
┌─────────────────────────────┐
│       Keyword Manager       │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│       Data Collector        │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│        Raw Storage          │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│      Cleaning Pipeline      │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│       NLP Processor         │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│     Discovery Engine        │
├─────────────────────────────┤
│ Frequency                   │
│ N-Gram                      │
│ TF-IDF                      │
│ Co-occurrence               │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│    Candidate Manager        │
└──────────────┬──────────────┘
               ↓
         Human Review
               ↓
       New Seed Keywords
```

---

# 13. Technology Stack

## 13.1 Programming Language

**Python 3.11+**

Alasan:

- ekosistem NLP kuat;
- mudah untuk data processing;
- scikit-learn;
- pandas;
- sentence-transformers;
- integrasi Ollama;
- cocok untuk local-first development.

## 13.2 Database

### MVP

**SQLite**

Digunakan untuk:

- kemudahan setup;
- local development;
- single-user environment.

### Future

**PostgreSQL**

Digunakan apabila:

- dataset membesar;
- multi-user;
- concurrent processing;
- deployment server.

## 13.3 NLP

MVP:

- pandas;
- scikit-learn;
- NLTK atau library NLP Bahasa Indonesia;
- regex.

Future:

- sentence-transformers;
- multilingual embeddings;
- HDBSCAN;
- BERTopic.

## 13.4 Local LLM

Optional pada MVP.

Future:

**Ollama**

Digunakan untuk:

- memberi nama cluster;
- merangkum cluster;
- membantu interpretasi keyword;
- mengklasifikasikan kandidat.

LLM tidak menjadi sumber utama perhitungan frekuensi atau statistik.

## 13.5 Interface

MVP:

**CLI / Python scripts**

Future:

**Streamlit**

---

# 14. Local-First Architecture

Sistem dirancang agar dapat berjalan tanpa VPS.

```text
┌──────────────────────────────┐
│          Laptop              │
│                              │
│ Python                       │
│ SQLite                       │
│ NLP                          │
│ Optional Ollama              │
│ Optional Streamlit           │
│                              │
└───────────────┬──────────────┘
                │
                │ Internet
                ↓
       External Data Sources
```

Internet hanya diperlukan ketika mengambil data dari sumber online yang didukung.

Analisis dapat dilakukan sepenuhnya secara lokal.

---

# 15. Data Source Strategy

Sistem menggunakan **source adapter**.

Contoh:

```text
collectors/
├── base.py
├── youtube.py
├── reddit.py
├── tiktok.py
├── x.py
└── web.py
```

Tidak semua source harus tersedia pada MVP.

Setiap source harus dievaluasi berdasarkan:

- API availability;
- Terms of Service;
- robots.txt;
- rate limits;
- authentication;
- data accessibility;
- privacy restrictions.

Sistem harus mengutamakan API resmi atau dataset yang memang tersedia untuk penggunaan tersebut.

---

# 16. Privacy & Data Governance

Sistem harus menerapkan prinsip **data minimization**.

Data yang diperlukan untuk analisis:

```text
comment text
source
timestamp
source reference
```

Data yang tidak diperlukan sebaiknya tidak disimpan.

Informasi seperti:

- nama lengkap;
- email;
- nomor telepon;
- lokasi presisi;
- profil personal;

tidak menjadi bagian dari dataset kecuali benar-benar diperlukan dan penggunaannya memiliki dasar yang sesuai.

Sistem tidak dirancang untuk melakukan profiling individu.

---

# 17. Non-Functional Requirements

## NFR-001 Local Execution

MVP harus dapat berjalan pada komputer lokal tanpa VPS.

## NFR-002 Reproducibility

Setiap pipeline harus dapat dijalankan kembali menggunakan raw dataset.

## NFR-003 Modularity

Collector, cleaning, dan discovery engine harus terpisah.

## NFR-004 Extensibility

Penambahan source baru tidak boleh memerlukan perubahan besar pada NLP pipeline.

## NFR-005 Logging

Sistem harus mencatat:

- collection start;
- collection finish;
- jumlah data;
- error;
- processing status;
- iteration.

## NFR-006 Configuration

Keyword dan parameter utama harus dapat dikonfigurasi tanpa mengubah source code.

---

# 18. MVP Acceptance Criteria

### AC-001
User dapat memasukkan minimal 5 seed keywords.

### AC-002
System dapat mengumpulkan dataset komentar dari minimal satu sumber yang didukung.

### AC-003
System menyimpan raw comments.

### AC-004
System menghasilkan cleaned comments.

### AC-005
System dapat mendeteksi duplicate comments.

### AC-006
System menghasilkan top keywords berdasarkan frequency.

### AC-007
System menghasilkan bigram dan trigram.

### AC-008
System menghasilkan TF-IDF score.

### AC-009
System menghasilkan co-occurrence results.

### AC-010
System menghasilkan minimal satu daftar candidate keywords.

### AC-011
User dapat approve/reject candidate keyword.

### AC-012
Approved keyword dapat digunakan pada iteration berikutnya.

### AC-013
Seluruh proses dapat dijalankan pada komputer lokal.

---

# 19. MVP Development Phases

## Phase 0 - Project Foundation

Output:

```text
Project structure
requirements.txt
README.md
SQLite database
configuration system
```

---

## Phase 1 - Seed Keyword Engine

Output:

```text
Keyword management
YAML configuration
Keyword validation
```

---

## Phase 2 - Data Collection

Output:

```text
Collector interface
First source adapter
Raw data storage
Collection logging
```

---

## Phase 3 - Cleaning Pipeline

Output:

```text
Text normalization
Tokenization
Stopword filtering
Duplicate detection
Basic spam filtering
```

---

## Phase 4 - Keyword Discovery

Output:

```text
Frequency analysis
N-gram
TF-IDF
Co-occurrence
```

---

## Phase 5 - Keyword Expansion

Output:

```text
Candidate generation
Candidate scoring
Human review
Iteration management
```

---

## Phase 6 - Dashboard

Output:

```text
Streamlit dashboard
Keyword explorer
Frequency chart
N-gram explorer
Candidate review
Iteration history
```

---

# 20. Future Development

Setelah MVP stabil:

```text
MVP
 ↓
Multi-source
 ↓
Embeddings
 ↓
Semantic similarity
 ↓
Clustering
 ↓
Topic modeling
 ↓
Local LLM
 ↓
Temporal analysis
 ↓
Automated scheduled collection
 ↓
Cloud/VPS deployment
```

---

# 21. Future Intelligence Layer

## Semantic Keyword Discovery

Tidak hanya mencari kata yang sama, tetapi menemukan kata yang memiliki makna atau konteks yang mirip.

```text
keyword_a
    ↓
embedding
    ↓
semantic search
    ↓
similar terms
```

## Topic Discovery

```text
Comments
    ↓
Embeddings
    ↓
Clustering
    ↓
Topic A
Topic B
Topic C
```

## Temporal Analysis

Sistem dapat melihat perubahan keyword:

```text
September
keyword_a ↑

October
keyword_b ↑

November
keyword_c ↑
```

---

# 22. Success Metrics

MVP tidak hanya dinilai dari jumlah komentar yang berhasil dikumpulkan.

### Data Quality

- duplicate rate;
- spam rate;
- cleaning success rate.

### Discovery Quality

- percentage of relevant candidates;
- candidate approval rate;
- number of new useful keywords per iteration.

### System Performance

- processing time;
- collection throughput;
- memory usage;
- database size.

### Reproducibility

- successful pipeline rerun rate;
- error rate.

---

# 23. Risks

## Risk 1 - Source Access

Platform dapat membatasi API atau akses data.

**Mitigation:**

Gunakan source adapter dan prioritaskan API/dataset yang tersedia secara sah.

## Risk 2 - Keyword Bias

Seed keyword dapat menyebabkan dataset terlalu bias.

**Mitigation:**

Gunakan iterative discovery dan evaluasi candidate keyword.

## Risk 3 - Slang

Bahasa internet berkembang cepat.

**Mitigation:**

Gunakan n-gram, co-occurrence, dan keyword expansion.

## Risk 4 - Spam

Spam dapat mendominasi frequency analysis.

**Mitigation:**

Duplicate detection dan spam filtering.

## Risk 5 - False Discovery

Kata yang sering muncul belum tentu relevan.

**Mitigation:**

Human-in-the-loop review.

## Risk 6 - Dataset Bias

Data dari satu platform tidak merepresentasikan seluruh populasi internet.

**Mitigation:**

Jangan mengklaim hasil sebagai representasi seluruh populasi internet. Tambahkan sumber secara bertahap dan tampilkan source distribution.

---

# 24. Example End-to-End Workflow

```text
USER
 │
 │ Seed Keywords
 ↓
KEYWORD MANAGER
 │
 ↓
COLLECTOR
 │
 ├── Source A
 └── Source B
 │
 ↓
RAW DATABASE
 │
 ↓
CLEANING
 │
 ↓
PROCESSED DATA
 │
 ├── Frequency
 ├── N-Gram
 ├── TF-IDF
 └── Co-occurrence
 │
 ↓
DISCOVERY ENGINE
 │
 ↓
CANDIDATE KEYWORDS
 │
 ↓
HUMAN REVIEW
 │
 ├── APPROVE
 │      ↓
 │   NEW SEED
 │
 └── REJECT
        ↓
      IGNORE
 │
 ↓
NEXT ITERATION
```

---

# 25. Definition of Done - MVP

MVP dinyatakan selesai ketika pengguna dapat melakukan proses berikut hanya dari komputer lokal:

```text
1. Memasukkan seed keyword
2. Menjalankan collection
3. Melihat jumlah data
4. Menyimpan raw data
5. Menjalankan cleaning
6. Melihat cleaned data
7. Menjalankan frequency analysis
8. Melihat top keywords
9. Melihat n-grams
10. Melihat TF-IDF
11. Melihat co-occurrence
12. Mendapatkan candidate keywords
13. Approve/reject kandidat
14. Menjalankan iteration berikutnya
15. Melihat riwayat discovery
```

Dengan demikian, sistem sudah membentuk **closed-loop keyword discovery pipeline**:

```text
SEED
 ↓
COLLECT
 ↓
CLEAN
 ↓
ANALYZE
 ↓
DISCOVER
 ↓
REVIEW
 ↓
EXPAND
 ↓
COLLECT AGAIN
```

Pipeline tersebut merupakan inti dari Ngulik versi pertama.
