function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('show');
}

function confirmDelete(form) {
    return confirm('Apakah Anda yakin ingin menghapus data ini?');
}

// Auto format angka ribuan pada input harga (tampilan saja, value tetap angka murni saat submit)
document.addEventListener('DOMContentLoaded', function () {

    document.querySelectorAll('.input-rupiah').forEach(function(el){

        // Format nilai awal saat halaman dibuka (Edit)
        if(el.value){
            el.value = formatRupiah(el.value);
        }

        // Saat fokus, hilangkan titik
        el.addEventListener('focus', function(){
            this.value = this.value.replace(/\./g, '');
        });

        // Saat keluar dari input, tampilkan format
        el.addEventListener('blur', function(){
            if(this.value){
                this.value = formatRupiah(this.value);
            }
        });

        // Sebelum submit, kirim angka murni
        el.form.addEventListener('submit', function(){
            el.value = el.value.replace(/\./g, '');
        });

    });

    function formatRupiah(value){
        let angka = value.toString().replace(/\D/g,'');
        return angka.replace(/\B(?=(\d{3})+(?!\d))/g,'.');
    }

});
