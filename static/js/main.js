function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('show');
}

function confirmDelete(form) {
    return confirm('Apakah Anda yakin ingin menghapus data ini?');
}

// Auto format angka ribuan pada input harga (tampilan saja, value tetap angka murni saat submit)
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.input-rupiah').forEach(function (el) {
        el.addEventListener('input', function () {
            let val = el.value.replace(/[^0-9]/g, '');
            el.value = val;
        });
    });

    // auto hide alert
    document.querySelectorAll('.alert-auto-hide').forEach(function (el) {
        setTimeout(function () {
            el.classList.remove('show');
        }, 4000);
    });
});
