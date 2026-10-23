<?php
require '/var/www/html/wp-load.php';
if (!is_blog_installed()) {
    fwrite(STDERR, "Conclua a instalacao do WordPress em http://localhost.\n");
    exit(1);
}

// Escolhe a qualidade JPEG mais proxima do tamanho solicitado, sem miniaturas.
function criar_imagem($arquivo, $tamanho, $largura, $altura) {
    mt_srand(42);
    $imagem = imagecreatetruecolor($largura, $altura);
    for ($y = 0; $y < $altura; $y++) {
        for ($x = 0; $x < $largura; $x++) {
            imagesetpixel($imagem, $x, $y, mt_rand(0, 0xffffff));
        }
    }
    $melhor = null;
    for ($qualidade = 40; $qualidade <= 95; $qualidade++) {
        ob_start();
        imagejpeg($imagem, null, $qualidade);
        $jpeg = ob_get_clean();
        if ($melhor === null || abs(strlen($jpeg) - $tamanho) < abs(strlen($melhor) - $tamanho)) {
            $melhor = $jpeg;
        }
    }
    imagedestroy($imagem);
    file_put_contents($arquivo, $melhor);
    return strlen($melhor);
}

$pasta = '/var/www/html/wp-content/uploads/trabalho3';
wp_mkdir_p($pasta);
$cenarios = array();
foreach (array('imagem-1mb' => 1000000, 'texto-400kb' => 400000, 'imagem-300kb' => 300000) as $nome => $tamanho) {
    $imagem = null;
    if ($nome === 'texto-400kb') {
        $texto = 'Texto para o teste de carga do WordPress. ';
        $conteudo = substr(str_repeat($texto, (int) ceil($tamanho / strlen($texto))), 0, $tamanho);
        $bytes = strlen($conteudo);
    } else {
        $arquivo = "$pasta/$nome.jpg";
        $grande = $nome === 'imagem-1mb';
        $bytes = criar_imagem($arquivo, $tamanho, $grande ? 1400 : 800, $grande ? 1000 : 600);
        if (abs($bytes - $tamanho) > $tamanho * 0.05) {
            fwrite(STDERR, "Imagem fora da tolerancia de 5%: $nome ($bytes bytes).\n");
            exit(1);
        }
        $imagem = "/wp-content/uploads/trabalho3/$nome.jpg";
        $conteudo = '<p>Teste de carga.</p><img src="' . $imagem . '" alt="Imagem do teste">';
    }
    $slug = "trabalho3-$nome";
    $existente = get_page_by_path($slug, OBJECT, 'post');
    $post = array('post_title' => "Teste $nome", 'post_name' => $slug, 'post_type' => 'post',
        'post_status' => 'publish', 'post_content' => $conteudo, 'comment_status' => 'closed');
    if ($existente) { $post['ID'] = $existente->ID; }
    $id = wp_insert_post($post, true);
    if (is_wp_error($id)) { fwrite(STDERR, $id->get_error_message()); exit(1); }
    $url = wp_parse_url(get_permalink($id));
    $home = wp_parse_url(home_url());
    $cenarios[$nome] = array('post' => $url['path'] . (isset($url['query']) ? '?' . $url['query'] : ''),
        'imagem' => $imagem, 'bytes' => $bytes,
        'host' => $home['host'] . (isset($home['port']) ? ':' . $home['port'] : ''));
}
file_put_contents("$pasta/cenarios.json", json_encode($cenarios, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
foreach ($cenarios as $nome => $dados) { echo "$nome: " . $dados['bytes'] . " bytes\n"; }
