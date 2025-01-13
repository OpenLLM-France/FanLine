<script>
    import AdminTestInterface from '$lib/admin_cmpnts/AdminTestInterface.svelte';
    import AdminSidebar from '$lib/admin_cmpnts/AdminSidebar.svelte';
    import AdminTimeline from '$lib/admin_cmpnts/AdminTimeline.svelte';
</script>

<div class="min-h-screen dark:bg-gray-900">
    <div class="flex min-h-screen">
        <AdminSidebar />
        <!-- Content area -->
        <div class="flex p-4 h-screen overflow-y-auto">
            <AdminTimeline />
        </div>
    </div>
</div>

<style>
    /* Les styles sont gérés par Tailwind CSS */
</style>
