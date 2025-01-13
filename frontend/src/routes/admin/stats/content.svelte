<script>
    import AdminChart from "$lib/admin_cmpnts/AdminChart.svelte";
    
    let test_data = [
        {
            name: "test",
            data: [1, 3, 5, 12],
            color: "#1C64F2",
        }
    ]
</script>

<div class="w-full p-4 h-screen overflow-y-auto">
    <div class="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
        <AdminChart main_value="2" unit="test" chart_data={test_data} height="200px" />
        <AdminChart main_value="2" unit="test" chart_data={test_data} height="200px" />
    </div>
</div>
